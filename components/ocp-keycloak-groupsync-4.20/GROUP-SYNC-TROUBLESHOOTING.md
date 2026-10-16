# DaSTOR group synchronization checks

## Status and logs

```sh
oc get groupsync dastor-keycloak-groupsync -n group-sync-operator -o yaml
oc get pods -n group-sync-operator
oc logs deployment/group-sync-operator-controller-manager -n group-sync-operator -c manager --tail=100
oc get groups.user.openshift.io
```

A successful reconciliation has a successful last-sync time and a success
condition. The upstream success reason is spelled `LastReconcileCycleSucceded`.
Groups may legitimately have no members until people are assigned in Keycloak.

## Authentication failures

The account belongs to the `openshift` realm, so both `realm` and `loginRealm`
are `openshift`. The Secret is `keycloak-group-sync` in `group-sync-operator`,
with `username` and `password` keys. Check that the account is enabled, its
password is not temporary and it has no required actions. The default admin-cli
client must allow direct access grants for this operator version. Do not reuse
an administrator's password as the synchronization account.

## Authorization failures

The account requires realm-management `view-users`, `query-users` and
`query-groups`. Confirm that it can read both groups and their members.
Do not grant realm-admin merely to hide an authorization error.

## TLS failures

Check `keycloak-certs:ca.crt` and the certificate currently served by
`keycloak.apps.dstr-rdg-opnsft.dastorllc.com`. Refresh trust after certificate
rotation. Keep certificate validation enabled; copying the public trust chain
is sufficient and does not require the private key.

## Missing nested groups

Compare the Keycloak API group tree with the OpenShift Groups. Check `scope: sub`
and the provider group filter. Keycloak API representations can omit nested
groups; a successful top-level reconciliation alone does not prove subgroup
membership synchronized. Record actual observed groups after deployment.

## Force a new sync

Update the GroupSync metadata annotation to request reconciliation:

```sh
oc annotate groupsync dastor-keycloak-groupsync -n group-sync-operator reconcile-now="$(date +%s)" --overwrite
```

This triggers the existing provider only; it does not fix nested-group discovery.
The instance Kustomization now includes the authorized `cluster-admins` role
binding, but the nested membership requires the helper below.

## Observed nested-group behavior on DaSTOR

On October 16, 2026, the provider synchronized `openshift-access` with member
`darleya`. A direct Keycloak query confirmed that the default group listing has
zero populated subgroups while the parent's children endpoint returns
`cluster-admins`. Operator 0.0.36 therefore reports success for the parent while
omitting the nested group. This is not an authentication or TLS failure.

## RDG admin membership workaround

On October 16, 2026, the authorized cluster-admin binding was applied and the
nested admin group was synchronized using `scripts/sync-cluster-admins.py`.
Run it with `--context <rdg-context>` to preview and add `--apply` to synchronize.
It fetches the exact Keycloak child group and all member pages before updating
OpenShift, including membership removals. It is a manual workaround; the existing
operator schedule still updates only the parent group. See README.md for commands.
