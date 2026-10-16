#!/usr/bin/env python3
"""Create initial Keycloak credentials through oc; never print their values."""
import argparse
import base64
import json
import secrets
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kubeconfig', required=True, help='Kubeconfig for the DaSTOR cluster')
args = parser.parse_args()
oc = ['oc', '--kubeconfig', args.kubeconfig]
expected = 'apps.dstr-rdg-opnsft.dastorllc.com'
check = subprocess.run(oc + ['get', 'ingress.config.openshift.io', 'cluster', '-o', 'json'], capture_output=True, text=True, check=True)
if json.loads(check.stdout)['spec']['domain'] != expected:
    sys.exit('Wrong cluster: ingress domain does not match DaSTOR. No Secrets created.')
subprocess.run(oc + ['get', 'namespace', 'keycloak'], check=True, stdout=subprocess.DEVNULL)

def ensure(name, generate, required):
    result = subprocess.run(oc + ['get', 'secret', name, '-n', 'keycloak', '--ignore-not-found', '-o', 'json'], capture_output=True, text=True, check=True)
    if result.stdout.strip():
        data = json.loads(result.stdout).get('data', {})
        if not all(key in data and base64.b64decode(data[key]) for key in required):
            sys.exit(name + ': existing Secret lacks required nonempty keys; left unchanged.')
        print(name + ': existing credentials preserved')
        return
    document = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': 'keycloak'}, 'type': 'Opaque', 'stringData': generate()}
    result = subprocess.run(oc + ['create', '-f', '-'], input=json.dumps(document), capture_output=True, text=True)
    if result.returncode:
        # Do not echo API responses that might include submitted Secret contents.
        sys.exit(name + ': creation failed; inspect namespace access and whether another process created it.')
    print(name + ': created with fresh random credentials')

ensure('keycloak-db-secret', lambda: {'username': 'keycloak', 'password': secrets.token_urlsafe(48)}, ['username', 'password'])
ensure('dastor-keycloak-realm-config', lambda: {'clientSecret': secrets.token_urlsafe(48)}, ['clientSecret'])
