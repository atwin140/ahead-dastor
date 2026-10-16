#!/usr/bin/env python3
"""Set up the DaSTOR GroupSync account, Kubernetes Secret and Keycloak trust."""
import argparse
import base64
import json
import secrets
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kubeconfig', required=True)
args = parser.parse_args()
oc = ['oc', '--kubeconfig', args.kubeconfig]
namespace = 'group-sync-operator'
host = 'https://keycloak.apps.dstr-rdg-opnsft.dastorllc.com'

def read(kind, name, ns=None, optional=False):
    cmd = oc + ['get', kind, name, '-o', 'json']
    if ns:
        cmd += ['-n', ns]
    if optional:
        cmd += ['--ignore-not-found']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None

def secret_data(name, ns):
    return {k: base64.b64decode(v).decode() for k, v in read('secret', name, ns)['data'].items()}

def write(document, verb):
    result = subprocess.run(oc + [verb, '-f', '-'], input=json.dumps(document), capture_output=True, text=True)
    if result.returncode:
        sys.exit('Kubernetes write failed for ' + document['metadata']['name'] + '; response omitted to protect credentials.')

if read('ingress.config.openshift.io', 'cluster')['spec']['domain'] != 'apps.dstr-rdg-opnsft.dastorllc.com':
    sys.exit('Wrong cluster; no changes made.')
read('namespace', namespace)
certificate = secret_data('cluster-wildcard-tls', 'openshift-ingress')['tls.crt']
context = ssl.create_default_context(cadata=certificate)
write({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'keycloak-certs', 'namespace': namespace}, 'data': {'ca.crt': certificate}}, 'apply')

def request(path, data=None, method=None, bearer=None, form=None):
    headers = {'Accept': 'application/json'}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    else:
        body = None
    req = urllib.request.Request(host + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        sys.exit('Keycloak request failed: HTTP ' + str(error.code) + ' at ' + path + '; response omitted.')

admin = secret_data('dastor-keycloak-initial-admin', 'keycloak')
token = request('/realms/master/protocol/openid-connect/token', form={'grant_type': 'password', 'client_id': 'admin-cli', 'username': admin['username'], 'password': admin['password']})['access_token']
realm = '/admin/realms/openshift'
username = 'dastor-group-sync'
users = request(realm + '/users?username=' + username + '&exact=true', bearer=token)
stored = read('secret', 'keycloak-group-sync', namespace, optional=True)
if stored:
    data = {k: base64.b64decode(v).decode() for k, v in stored.get('data', {}).items()}
    if data.get('username') != username or not data.get('password') or data['password'] == 'REPLACE_USING_BOOTSTRAP_HELPER':
        sys.exit('Existing credentials are not usable; left unchanged. Rotate them deliberately.')
    password = data['password']
else:
    if users:
        sys.exit('Keycloak account already exists without its Kubernetes Secret; refusing to reset its password.')
    password = secrets.token_urlsafe(48)
    write({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'keycloak-group-sync', 'namespace': namespace}, 'type': 'Opaque', 'stringData': {'username': username, 'password': password}}, 'create')
if not users:
    request(realm + '/users', method='POST', bearer=token, data={'username': username, 'enabled': True, 'firstName': 'DaSTOR', 'lastName': 'Group Sync', 'email': 'dastor-group-sync@service.invalid', 'emailVerified': True, 'requiredActions': [], 'credentials': [{'type': 'password', 'value': password, 'temporary': False}]})
    users = request(realm + '/users?username=' + username + '&exact=true', bearer=token)
if len(users) != 1:
    sys.exit('Expected exactly one synchronization account.')
management = request(realm + '/clients?clientId=realm-management', bearer=token)
client_id = management[0]['id']
roles = [request(realm + '/clients/' + client_id + '/roles/' + name, bearer=token) for name in ['view-users', 'query-users', 'query-groups']]
request(realm + '/users/' + users[0]['id'] + '/role-mappings/clients/' + client_id, method='POST', bearer=token, data=roles)
sync_token = request('/realms/openshift/protocol/openid-connect/token', form={'grant_type': 'password', 'client_id': 'admin-cli', 'username': username, 'password': password})['access_token']
groups = request(realm + '/groups', bearer=sync_token)
print('Synchronization account authenticated; realm groups readable: ' + str(len(groups)))
print('Credentials and TLS trust configured; no credential values displayed.')
