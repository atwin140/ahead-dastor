#!/usr/bin/env python3
"""Preview or synchronize RDG cluster-admins from its exact Keycloak subgroup."""
import argparse
import base64
import datetime
import json
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True, help='RDG oc context')
    parser.add_argument('--apply', action='store_true', help='Write membership; default is preview only')
    args = parser.parse_args()
    oc = ['oc', '--context', args.context, '--request-timeout=20s']

    def read(kind, name, namespace=None):
        command = oc + ['get', kind, name, '-o', 'json']
        if namespace:
            command += ['-n', namespace]
        return json.loads(subprocess.check_output(command, text=True))

    domain = read('ingress.config.openshift.io', 'cluster')['spec']['domain']
    if domain != 'apps.dstr-rdg-opnsft.dastorllc.com':
        raise RuntimeError('Wrong cluster; no changes made')
    namespace = 'group-sync-operator'
    secret = read('secret', 'keycloak-group-sync', namespace)
    credentials = {key: base64.b64decode(secret['data'][key]).decode()
                   for key in ('username', 'password')}
    ca = read('configmap', 'keycloak-certs', namespace)['data']['ca.crt']
    context = ssl.create_default_context(cadata=ca)
    host = 'https://keycloak.' + domain
    token = None

    def request(path, form=None):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        req = urllib.request.Request(host + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, context=context, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError('Keycloak HTTP ' + str(error.code) + '; membership unchanged') from None

    token = request('/realms/openshift/protocol/openid-connect/token',
                    {'grant_type': 'password', 'client_id': 'admin-cli', **credentials})['access_token']

    def pages(path):
        result = []
        first = 0
        while True:
            page = request(path + '?' + urllib.parse.urlencode({'first': first, 'max': 100}))
            if not isinstance(page, list):
                raise RuntimeError('Unexpected Keycloak response; membership unchanged')
            if not page:
                return result
            result.extend(page)
            first += len(page)

    root = '/admin/realms/openshift'
    parents = [g for g in pages(root + '/groups') if g.get('path') == '/openshift-access']
    if len(parents) != 1:
        raise RuntimeError('Expected exactly one /openshift-access group; membership unchanged')
    children = pages(root + '/groups/' + urllib.parse.quote(parents[0]['id'], safe='') + '/children')
    matches = [g for g in children if g.get('path') == '/openshift-access/cluster-admins']
    if len(matches) != 1:
        raise RuntimeError('Expected exact /openshift-access/cluster-admins subgroup; membership unchanged')
    source = matches[0]
    members = pages(root + '/groups/' + urllib.parse.quote(source['id'], safe='') + '/members')
    if any(not isinstance(m.get('username'), str) or not m['username'] for m in members):
        raise RuntimeError('Invalid member username; membership unchanged')
    desired = sorted({m['username'] for m in members})
    group = read('groups.user.openshift.io', 'cluster-admins')
    current = set(group.get('users') or [])
    print(json.dumps({'group': 'cluster-admins', 'source': source['path'],
                      'add': sorted(set(desired) - current),
                      'remove': sorted(current - set(desired)), 'desired': desired}, indent=2))
    if not args.apply:
        print('Preview only; use --apply to synchronize membership.')
        return
    # Exact replacement propagates removals too. Read every page before writing,
    # and reject concurrent updates using the resourceVersion precondition.
    patch = {'metadata': {'resourceVersion': group['metadata']['resourceVersion'],
                          'annotations': {
                              'dastorllc.com/keycloak-group-path': source['path'],
                              'dastorllc.com/keycloak-group-id': source['id'],
                              'dastorllc.com/membership-sync-time': datetime.datetime.now(datetime.timezone.utc).isoformat()}},
             'users': desired}
    subprocess.run(oc + ['patch', 'groups.user.openshift.io', 'cluster-admins', '--type=merge',
                         '--patch-file=/dev/stdin'], input=json.dumps(patch), text=True, check=True)
    actual = read('groups.user.openshift.io', 'cluster-admins').get('users') or []
    if sorted(actual) != desired:
        raise RuntimeError('Membership verification failed')
    print('Verified OpenShift membership matches all ' + str(len(desired)) + ' Keycloak members.')


if __name__ == '__main__':
    main()
