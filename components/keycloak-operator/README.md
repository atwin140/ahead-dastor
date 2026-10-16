# DaSTOR Keycloak

Prepared October 16, 2026 from the existing Keycloak operator component for the
DaSTOR RDG cluster. Manually deployed on October 16, 2026, with the operator,
PostgreSQL, Keycloak and realm import verified healthy. The Argo CD Applications
have been prepared for repository deployment but have not been registered.

## Cluster-specific settings

| Setting | Value |
| --- | --- |
| Namespace | `keycloak` |
| Keycloak resource | `dastor-keycloak` |
| URL | `https://keycloak.apps.dstr-rdg-opnsft.dastorllc.com` |
| Realm | `openshift` (display name: DaSTOR OpenShift) |
| OIDC client | `dastor-openshift` |
| OpenShift provider name expected by callback | `keycloak` |
| Callback | `https://oauth-openshift.apps.dstr-rdg-opnsft.dastorllc.com/oauth2callback/keycloak` |
| Operator channel | `stable-v26.4` |
| Initial CSV | `rhbk-operator.v26.4.16-opr.1` |
| Catalog | `redhat-operators` / `openshift-marketplace` |
| StorageClass | `powerstore-fc` |
| Database / backup volume sizes | 10 GiB / 30 GiB |
| Backup schedule | 02:00 America/Chicago daily; retain 30 days |

The operator version and storage class were verified against the live cluster.
No Keycloak namespace or subscription existed during inspection. PostgreSQL 15
uses the Red Hat RHEL9 image for both the database and `pg_dump`, avoiding the
source component's mixed database/client images. The PostgreSQL image retains
the vendor's floating `latest` tag within the PostgreSQL 15 repository; pin both
references to the same verified digest before introducing immutable image
promotion. Registry entitlement and image pulls have not been tested.

There is one Keycloak instance and one PostgreSQL replica. This is a persistent
bootstrap deployment, not a highly available database service. The operator
selects its matching Keycloak server image. OLM install and upgrade approval is
Manual; `startingCSV` is an initial version selection, not a permanent lock.

## Layout and GitOps registration

- `base/`: namespace, namespace-scoped GitOps permissions, OperatorGroup,
  and Subscription.
- `overlays/dastor/`: persistent PostgreSQL, backups, Keycloak and edge Route.
- `overlays/dastor-realm-config/`: separate one-time realm import.
- `scripts/bootstrap-secrets.py`: generate credentials without putting them in Git.
- Repository `groups/RDG/`: three manually synced Argo CD Applications.

Application sources use the existing repository
`https://github.com/atwin140/ahead-dastor.git` and its `sandbox` branch. They use
the existing `platform-services` project and `openshift-gitops` namespace.
Automatic sync, automatic pruning and cascading deletion finalizers are omitted.
The existing `clusters/hub` parent does not include `groups/RDG`; register this
group explicitly, or include it in the intended RDG parent when one is defined.
The group was not added to a shared group so other clusters do not receive it.

After committing and pushing these files to `sandbox`, register the Applications:

```sh
oc --kubeconfig /path/to/dastor-kubeconfig apply -k groups/RDG
```

The AppProject must exist, and the GitOps controller needs permission to create
the namespace and bootstrap its Role and RoleBinding. Namespace RBAC in this
component does not grant namespace creation or cluster-admin access. OLM creates
the operator's own cluster permissions through its reviewed InstallPlan.

## Deployment sequence

1. Manually sync `dastor-keycloak-operator`.
2. Review the generated InstallPlan in `keycloak`, including dependencies,
   and approve it. Wait for `rhbk-operator.v26.4.16-opr.1` to reach Succeeded
   and the Keycloak/KeycloakRealmImport CRDs to be Established.
3. Create fresh credentials in the target namespace:

   ```sh
   python3 components/keycloak-operator/scripts/bootstrap-secrets.py \
     --kubeconfig /path/to/dastor-kubeconfig
   ```

   The helper verifies the ingress domain, creates `keycloak-db-secret`
   (`username`, `password`) and `dastor-keycloak-realm-config` (`clientSecret`),
   and preserves existing Secrets. It does not print values or write them to
   disk. Retain them in the organization's secret-management system. Never
   regenerate the database password while reusing an initialized PostgreSQL PVC:
   changing the Secret alone does not rotate the database role password.
4. Manually sync `dastor-keycloak`. Verify PostgreSQL readiness, PVC binding,
   Keycloak readiness and the route before proceeding.
5. Manually sync `dastor-keycloak-realm`. Wait for the realm import `Done=True`,
   then verify the realm, client and callback in the Keycloak admin console.
   The operator creates `dastor-keycloak-initial-admin` in `keycloak` with the
   initial admin username/password. Retrieve those through your usual secure
   Secret access process and establish permanent admin access with MFA.

Each Application must be synced separately in this order; sync waves inside
individual Applications do not coordinate readiness across Applications.

## Ingress and OpenShift login

The explicit edge Route uses the cluster's default ingress certificate and
redirects HTTP to HTTPS. The canonical HTTPS hostname is fixed in Keycloak.
The router replaces incoming forwarded headers, and Keycloak uses
`proxy.headers: xforwarded`. The operator's own Ingress creation is disabled.
No unused service certificate annotation or TLS Secret is requested.

The preceding certificate investigation found ingress using a temporary
self-signed certificate while GoDaddy validation returned 401. This route does
not resolve that problem. Verify the current ingress certificate and restore a
trusted chain before enabling OpenShift OIDC authentication, or deliberately
configure a trusted CA bundle for the provider.

The realm import prepares only the DaSTOR client and its exact callback.
It does not modify the live OpenShift OAuth configuration. For a later OIDC
provider named `keycloak`, use:

- Issuer: `https://keycloak.apps.dstr-rdg-opnsft.dastorllc.com/realms/openshift`
- Client ID: `dastor-openshift`
- Client secret: the value in `keycloak/dastor-keycloak-realm-config:clientSecret`,
  securely copied to a dedicated Secret in `openshift-config`.
- Claims: `preferredUsername: [preferred_username]`, `name: [name]`,
  `email: [email]`; request the `groups` scope if consuming that claim.

Preserve existing identity providers when configuring OAuth. Realm groups do not
automatically create OpenShift groups, synchronize membership, or grant cluster
roles. No users, passwords, RBAC role grants or group-sync deployment are seeded.
The `KeycloakRealmImport` is an initial import and does not reconcile subsequent
changes to an existing realm; use the admin API/UI for later changes. Do not
delete a live realm merely to reapply this initial import.

## Storage and backups

PostgreSQL uses the namespace-assigned UID and volume group through OpenShift's
restricted SCC. The database and backup pods do not request fixed UIDs, fixed
fsGroups or anyuid access. Actual PowerStore CSI permissions must be verified
when the pods start. No StorageClass is created by this component.

Database PVCs are retained by the StatefulSet's default retention policy, but
the existing `powerstore-fc` StorageClass has reclaimPolicy Delete: deleting a
PVC can delete its backing volume. The backup PVC is a separate volume on the
same storage system; it is not off-site disaster recovery. Backups contain
sensitive identity data. Protect and export them through the normal backup
system and test restoration before production use. A failed dump is never
renamed as a completed `.sql` backup. The 30 GiB backup volume needs capacity
monitoring; retention is by age, not space.

## Validation

```sh
oc kustomize components/keycloak-operator/base
oc kustomize components/keycloak-operator/overlays/dastor
oc kustomize components/keycloak-operator/overlays/dastor-realm-config
oc kustomize groups/RDG
```

These commands render locally. All four builds passed during preparation.
The custom resources were also checked against the official Keycloak 26.4.0
CRD schemas. This is structural validation, not a deployment or runtime test.
The secret helper passed syntax and mocked behavior checks and was then run
against DaSTOR to generate fresh credentials. The operator CSV reached Succeeded;
PostgreSQL and Keycloak reached Ready; both PowerStore PVCs bound; the realm
import reached Done. A manual backup job completed successfully after database
readiness. The public realm discovery endpoint, exact client callback and imported
client-secret equality were verified through the Keycloak API using an explicit
trust file for the existing self-signed ingress certificate. Passwords and client
secrets were not printed. Restore testing and end-user OIDC login remain untested;
OpenShift OAuth has not been modified. The initial backup check started during
database initialization and failed; it was removed after a fresh check succeeded.

After deploying:

```sh
oc --kubeconfig /path/to/dastor-kubeconfig get csv,pods,pvc -n keycloak
oc --kubeconfig /path/to/dastor-kubeconfig get keycloak dastor-keycloak -n keycloak
oc --kubeconfig /path/to/dastor-kubeconfig get keycloakrealmimport dastor-keycloak-realm-openshift -n keycloak
oc --kubeconfig /path/to/dastor-kubeconfig get route dastor-keycloak -n keycloak
oc --kubeconfig /path/to/dastor-kubeconfig get cronjob keycloak-postgresql-backup -n keycloak
```

References: [Red Hat 26.4 Operator Guide](https://docs.redhat.com/en/documentation/red_hat_build_of_keycloak/26.4/html-single/operator_guide/index),
[Keycloak 26.4.0 CRDs](https://github.com/keycloak/keycloak-k8s-resources/tree/26.4.0/kubernetes).
