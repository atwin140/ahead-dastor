# DaSTOR Keycloak Group Sync

Manually deployed and verified on October 16, 2026.
This component targets the DaSTOR cluster on OpenShift 4.22. The historical
`ocp-keycloak-groupsync-4.20` directory name is retained for repository compatibility.

## Configuration

- Community Group Sync Operator: `group-sync-operator.v0.0.36`, channel `alpha`.
- Catalog: `community-operators` in `openshift-marketplace`.
- Namespace: `group-sync-operator`.
- GroupSync: `dastor-keycloak-groupsync`.
- Keycloak: `https://keycloak.apps.dstr-rdg-opnsft.dastorllc.com`.
- Realm and login realm: `openshift`.
- Account: `dastor-group-sync`, with realm-management `view-users`, `query-users`
  and `query-groups` roles. This is a dedicated machine user because version
  0.0.36's Keycloak provider uses username/password authentication through admin-cli.
- Credential Secret: `group-sync-operator/keycloak-group-sync` (`username`, `password`).
- Trust ConfigMap: `group-sync-operator/keycloak-certs` (`ca.crt`).
- Schedule: every 15 minutes. Sync root: `openshift-access`, with subtree scope.
- Group pruning is disabled. Existing synchronized group membership is still
  updated on each successful run; disabling pruning does not freeze membership.

The operator version was verified in DaSTOR's live catalog. This is a community
operator; the component directory name does not assert Red Hat support or a
certification for a particular OpenShift release. Operator installation and
future upgrades use manual InstallPlan approval.

## Manual installation

From the repository root, using the DaSTOR kubeconfig:

```sh
oc --kubeconfig /path/to/dastor-kubeconfig apply -k components/ocp-keycloak-groupsync-4.20/operators/group-sync-operator
```

Review the generated InstallPlan, verify its only CSV is
`group-sync-operator.v0.0.36`, approve that plan and wait for its CSV to reach
Succeeded and `groupsyncs.redhatcop.redhat.io` to become Established.

Provision the dedicated realm account, fresh password and TLS trust:

```sh
python3 components/ocp-keycloak-groupsync-4.20/scripts/bootstrap-keycloak.py --kubeconfig /path/to/dastor-kubeconfig
```

The helper checks the cluster domain, uses the initial Keycloak admin credentials
in memory, creates a fresh synchronization account, assigns only the three read
roles and verifies that the account can authenticate and list realm groups. It
creates the Kubernetes Secret without printing passwords or writing them to disk.
Existing credentials are preserved on rerun. An existing account without its
Secret causes the helper to stop rather than reset the password silently.
If the initial admin credentials have been retired, use a current admin session
to provision the equivalent account and Secret through your normal process.

Then apply the synchronization resource:

```sh
oc --kubeconfig /path/to/dastor-kubeconfig apply -k components/ocp-keycloak-groupsync-4.20/instances/keycloak-group-sync
oc --kubeconfig /path/to/dastor-kubeconfig get groupsync dastor-keycloak-groupsync -n group-sync-operator -o yaml
oc --kubeconfig /path/to/dastor-kubeconfig get groups.user.openshift.io
```

The component root and `overlays/dastor` render both installation stages for
inspection. For a first deployment, use the staged commands above; rendering
both stages does not make OLM establish the CRD before applying the GroupSync CR.
`overlays/local` is a compatibility alias to the DaSTOR overlay.

The two example Secret/ConfigMap YAML files in `instances/keycloak-group-sync`
are excluded from all Kustomizations. Do not apply their placeholder values;
use the helper or your secret-management system instead.

## Access and group names

Synchronization creates OpenShift Group objects; it does not configure OpenShift
OAuth, create OpenShift user identities or grant roles by itself. OpenShift OIDC
must use `preferred_username` to align with the usernames produced by this
provider. The prepared Keycloak OIDC client is `dastor-openshift`.

`30-cluster-admin-binding.yaml` is an optional, excluded manifest binding the
short group name `cluster-admins` to `cluster-admin`. It is not part of the normal
deployment. Apply it only when that access has explicitly been requested.
Group names must match the actual synchronized names; slash-delimited Keycloak
paths are not valid OpenShift group names.

## TLS and rotation

TLS verification remains enabled. The bootstrap helper copies the current
public certificate chain from `openshift-ingress/cluster-wildcard-tls` into the
trust ConfigMap. The current ingress certificate is self-signed. After changing
or renewing it, refresh the ConfigMap with the appropriate trust chain and
trigger a reconciliation; for a publicly trusted certificate, ensure the
ConfigMap includes the issuing trust anchor, or remove the custom `ca` reference
when the operator's system trust is sufficient. Never copy `tls.key`.

The provider password is generated once. Rotate the Keycloak password and
Kubernetes Secret together through the organization's secret-management process;
rerunning bootstrap intentionally preserves an existing password.

## GitOps

The repository's `groups/RDG` contains separate `dastor-groupsync-operator` and
`dastor-groupsync` Applications. They use `platform-services`, the RDG branch and
manual sync. Commit and push before registering those Applications. The instance
Application depends on runtime credentials and trust being provisioned first.
Manual deployment does not register or sync Applications automatically.

## Sources

- [Group Sync Operator](https://github.com/redhat-cop/group-sync-operator)
- [Version 0.0.36 Keycloak provider](https://github.com/redhat-cop/group-sync-operator/blob/v0.0.36/pkg/syncer/keycloak.go)

## Verified deployment result

- CSV `group-sync-operator.v0.0.36`: Succeeded.
- Operator pod: 2/2 Ready.
- GroupSync: `ReconcileSuccess=True`, reason `LastReconcileCycleSucceded`.
- Successful synchronization verified at 2026-10-16T16:34:18Z.
- OpenShift group `openshift-access` contains `darleya`.
- No cluster-admin binding was applied; OpenShift OAuth was not modified.

**Nested-group limitation:** Keycloak 26.4's default group listing omits the
`subGroups` array even though a separate children request returns `cluster-admins`.
The catalog operator's 0.0.36 Keycloak provider follows only the nested groups
present in that listing. Consequently, `scope: sub` is configured but the nested
`cluster-admins` group was not synchronized. The top-level group synchronization
is verified; nested synchronization requires a provider compatibility fix or a
separately agreed group layout. Do not assume the success condition covers nested
groups, and do not restructure live Keycloak groups solely to hide this limitation.

Repository files and Applications were prepared alongside the manual deployment.
The manual deployment did not register the Applications in Argo CD.
