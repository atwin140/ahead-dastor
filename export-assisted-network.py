#!/usr/bin/env python3
"""Query running OCP nodes and export four-port Assisted Installer NMState YAML."""
import argparse
import ipaddress
import json
import pathlib
import re
import subprocess
import sys

# Executed read-only inside /host. Markers separate JSON and text from oc chatter.
COLLECT = r'''
set -eu
printf '\n__EXPORT_ADDR__\n'
ip -d -j address show
printf '\n__EXPORT_ROUTE4__\n'
ip -j -4 route show table main
printf '\n__EXPORT_ROUTE6__\n'
ip -j -6 route show table main
printf '\n__EXPORT_NICS__\n'
for p in /sys/class/net/*; do
  [ -e "$p/device" ] || continue
  [ "$(cat "$p/type")" = 1 ] || continue
  n=${p##*/}
  carrier=$(cat "$p/carrier" 2>/dev/null || printf 0)
  speed=$(cat "$p/speed" 2>/dev/null || printf 0)
  mac=$(ethtool -P "$n" | awk '/Permanent address:/ {print $3}')
  printf '%s\t%s\t%s\t%s\n' "$n" "$carrier" "$speed" "$mac"
done
printf '\n__EXPORT_MEMBERS__\n'
cat "/sys/class/net/$1/bonding/slaves"
printf '\n__EXPORT_OPTIONS__\n'
profile=$(nmcli -g GENERAL.CONNECTION device show "$1")
nmcli -g bond.options connection show "$profile"
printf '\n__EXPORT_OVS__\n'
ovs-vsctl list-ifaces br-ex
printf '\n__EXPORT_RESOLV__\n'
cat /etc/resolv.conf
printf '\n__EXPORT_END__\n'
'''


def run(args, timeout=240):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f"Command failed: {' '.join(args[:5])}\n{result.stderr[-3000:]}")
    return result.stdout


def parse_capture(text):
    parts = re.split(r'^__EXPORT_([A-Z0-9]+)__\s*$', text, flags=re.M)
    sections = dict(zip(parts[1::2], parts[2::2]))
    required = {'ADDR', 'ROUTE4', 'ROUTE6', 'NICS', 'MEMBERS', 'OPTIONS', 'OVS', 'RESOLV', 'END'}
    if not required <= sections.keys():
        raise ValueError('Incomplete host capture; check oc debug permissions and host utilities.')
    for key in ('ADDR', 'ROUTE4', 'ROUTE6'):
        sections[key] = json.loads(sections[key])
    return sections


def yaml_text(value, level=0):
    """Emit basic YAML using JSON-quoted scalars (no third-party dependencies)."""
    indent = '  ' * level
    rows = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                rows.append(f'{indent}{key}:')
                rows.append(yaml_text(item, level + 1))
            else:
                rows.append(f'{indent}{key}: {json.dumps(item)}')
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                rows.append(f'{indent}-')
                rows.append(yaml_text(item, level + 1))
            else:
                rows.append(f'{indent}- {json.dumps(item)}')
    return '\n'.join(rows)


def build(node, capture, bond, expected):
    nics = []
    for line in capture['NICS'].strip().splitlines():
        name, carrier, speed, mac = line.split('\t')
        nics.append(dict(name=name, carrier=carrier == '1', speed=int(speed), mac=mac.lower()))
    selected = sorted((nic for nic in nics if nic['carrier']), key=lambda nic: nic['name'])
    if len(selected) != expected:
        raise ValueError(f"Expected {expected} physical NICs with carrier, found {len(selected)}: "
                         + ', '.join(n['name'] for n in selected))
    names = [nic['name'] for nic in selected]
    members = capture['MEMBERS'].split()
    if not set(members) <= set(names):
        raise ValueError('An existing bond member has no carrier; refusing to silently omit it.')
    for nic in selected:
        if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', nic['mac']) or nic['mac'] == '00:00:00:00:00:00':
            raise ValueError(f"Cannot determine permanent MAC for {nic['name']}")
    if len({nic['mac'] for nic in selected}) != len(selected):
        raise ValueError('Duplicate permanent NIC MAC addresses.')
    options = dict(part.strip().split('=', 1) for part in capture['OPTIONS'].strip().split(',') if '=' in part)
    mode = options.pop('mode', '')
    mode = {'4': '802.3ad', '1': 'active-backup', '2': 'balance-xor'}.get(mode, mode)
    if mode != '802.3ad':
        raise ValueError(f'Expected existing LACP bond, found mode {mode!r}.')
    if any(nic['speed'] <= 0 for nic in selected) or len({nic['speed'] for nic in selected}) != 1:
        raise ValueError('LACP ports must have a known, matching link speed.')
    options.setdefault('miimon', '100')
    interfaces = capture['ADDR']
    bonds = [i for i in interfaces if i['ifname'] == bond]
    if len(bonds) != 1:
        raise ValueError(f'Bond {bond} not found.')
    bond_state = bonds[0]
    vlans = [i for i in interfaces if i.get('linkinfo', {}).get('info_kind') == 'vlan'
             and (i.get('link') == bond or i.get('link_index') == bond_state['ifindex'])]
    uplinks = [i for i in vlans if i['ifname'] in capture['OVS'].split()]
    if len(uplinks) != 1:
        raise ValueError('Expected exactly one VLAN on this bond used as the br-ex uplink.')
    vlan = uplinks[0]
    internal = {a['address'] for a in node['status']['addresses'] if a['type'] == 'InternalIP'}
    sources = [i for i in interfaces if any(a.get('local') in internal for a in i.get('addr_info', []))]
    if len(sources) != 1 or sources[0]['ifname'] not in ('br-ex', vlan['ifname']):
        raise ValueError('Cannot unambiguously locate node InternalIP on br-ex or its VLAN.')
    source = sources[0]
    addresses = [a for a in source['addr_info'] if a.get('local') in internal]
    if {a['local'] for a in addresses} != internal:
        raise ValueError('Not all node InternalIPs were found on the primary interface.')
    mtu = source['mtu']
    disabled = {'ipv4': {'enabled': False}, 'ipv6': {'enabled': False}}
    desired = [{'name': name, 'type': 'ethernet', 'state': 'up', 'mtu': mtu, **disabled} for name in names]
    desired.append({'name': bond, 'type': 'bond', 'state': 'up', 'mtu': mtu,
                    'link-aggregation': {'mode': mode, 'options': options, 'port': names}, **disabled})
    target = {'name': vlan['ifname'], 'type': 'vlan', 'state': 'up', 'mtu': mtu,
              'vlan': {'base-iface': bond, 'id': vlan['linkinfo']['info_data']['id']}}
    routes = []
    for family, key in (('inet', 'ipv4'), ('inet6', 'ipv6')):
        family_addrs = [a for a in addresses if a['family'] == family]
        target[key] = {'enabled': bool(family_addrs)}
        if not family_addrs:
            continue
        target[key].update({'dhcp': False, 'address': [
            {'ip': a['local'], 'prefix-length': a['prefixlen']} for a in family_addrs]})
        if family == 'inet6':
            target[key]['autoconf'] = False
        for route in capture['ROUTE4' if family == 'inet' else 'ROUTE6']:
            if route.get('dst') != 'default' or route.get('dev') != source['ifname']:
                continue
            if 'gateway' not in route:
                raise ValueError('Default route without gateway is unsupported.')
            entry = {'destination': '0.0.0.0/0' if family == 'inet' else '::/0',
                     'next-hop-address': route['gateway'], 'next-hop-interface': vlan['ifname'], 'table-id': 254}
            if 'metric' in route:
                entry['metric'] = route['metric']
            routes.append(entry)
    if not routes:
        raise ValueError('No primary default gateway found in the main routing table.')
    dns, search = [], []
    for line in capture['RESOLV'].splitlines():
        tokens = line.split('#', 1)[0].split()
        if tokens and tokens[0] == 'nameserver' and len(tokens) > 1:
            addr = ipaddress.ip_address(tokens[1].split('%')[0])
            if addr.is_loopback or addr.is_link_local:
                raise ValueError('Host DNS uses a local/link-local resolver; supply real upstream DNS manually.')
            dns.append(tokens[1])
        elif tokens and tokens[0] in ('search', 'domain'):
            search = tokens[1:]
    if not dns:
        raise ValueError('No upstream DNS servers in host resolv.conf.')
    resolver = {'server': list(dict.fromkeys(dns))}
    if search:
        resolver['search'] = search
    desired.append(target)
    config = {'interfaces': desired, 'dns-resolver': {'config': resolver}, 'routes': {'config': routes}}
    mappings = [{'mac_address': n['mac'], 'logical_nic_name': n['name']} for n in selected]
    report = {'node': node['metadata']['name'], 'nics': selected, 'old_bond_members': members,
              'vlan': target['vlan'], 'addresses': addresses,
              'review': 'Confirm all four switch ports share the LACP port channel and allow this VLAN. '
                        'Current InternalIPs are exported as static; reserve any DHCP-assigned IPs. '
                        'Only primary InternalIPs and default routes are exported; review extra addresses/static routes.'}
    return config, mappings, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='assisted-network-export', help='New output directory (must not exist)')
    parser.add_argument('--node', action='append', help='Limit to a node; repeat for multiple nodes')
    parser.add_argument('--selector', help='oc node label selector')
    parser.add_argument('--bond', default='bond0')
    parser.add_argument('--expected-nics', type=int, default=4)
    args = parser.parse_args()
    dest = pathlib.Path(args.output)
    if dest.exists():
        parser.error('Output directory already exists; choose a new path to avoid mixing exports.')
    command = ['oc', 'get', 'nodes', '-o', 'json']
    if args.selector:
        command += ['-l', args.selector]
    nodes = json.loads(run(command))['items']
    if args.node:
        wanted = set(args.node)
        nodes = [n for n in nodes if n['metadata']['name'] in wanted]
        missing = wanted - {n['metadata']['name'] for n in nodes}
        if missing:
            parser.error('Nodes not found: ' + ', '.join(sorted(missing)))
    if not nodes:
        parser.error('No nodes selected.')
    dest.mkdir(parents=True)
    (dest / 'raw').mkdir()
    payload, reports, errors = [], [], []
    for node in sorted(nodes, key=lambda n: n['metadata']['name']):
        name = node['metadata']['name']
        print(f'Collecting {name}...', flush=True)
        try:
            raw = run(['oc', 'debug', f'node/{name}', '--', 'chroot', '/host',
                       'bash', '-c', COLLECT, 'export-network', args.bond])
            (dest / 'raw' / f'{name}.txt').write_text(raw)
            config, mappings, report = build(node, parse_capture(raw), args.bond, args.expected_nics)
            network_yaml = '# Exported for Assisted Installer; review inventory.json before use.\n' + yaml_text(config) + '\n'
            (dest / f'{name}.yaml').write_text(network_yaml)
            (dest / f'{name}.mac-map.json').write_text(json.dumps(mappings, indent=2) + '\n')
            payload.append({'network_yaml': network_yaml, 'mac_interface_map': mappings})
            reports.append(report)
            print(f'  Wrote {name}.yaml ({len(mappings)} NICs)')
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            errors.append({'node': name, 'error': str(exc)})
            print(f'  FAILED: {exc}', file=sys.stderr)
    (dest / 'inventory.json').write_text(json.dumps({'nodes': reports, 'errors': errors}, indent=2) + '\n')
    if errors:
        print('Export incomplete: see inventory.json. Combined API payload was not written.', file=sys.stderr)
        return 1
    (dest / 'static-network-config.json').write_text(json.dumps({'static_network_config': payload}, indent=2) + '\n')
    print(f'Export complete: {dest.resolve()}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
