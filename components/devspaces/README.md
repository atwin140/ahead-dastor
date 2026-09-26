# DaSTOR Dev Spaces deployment through Argo CD

Prepared on 2026-09-26. Files only: no manifests were applied, no InstallPlans were approved, and no Argo CD applications were created or synced during preparation. Cluster inspection used read-only requests with `~/dastor-kubeconfig`. No credentials are included.

## Selected versions and observed cluster settings

| Setting | Value |
| --- | --- |
| OpenShift | 4.22.14 |
| Dev Spaces operator | **3.30.1** — `devspacesoperator.v3.30.1` |
| Dev Spaces channel | `stable` |
| Dev Workspace operator | **0.43.0** — `devworkspace-operator.v0.43.0` |
| Dev Workspace channel | `fast` |
| Catalog | `redhat-operators` in `openshift-marketplace` |
| Approval | **Manual for both operator subscriptions** |
| Operator namespace | `openshift-operators` |
| Instance namespace | `openshift-devspaces` |
| Argo CD namespace / project | `openshift-gitops` / `platform-services` |
| Repository | `https://github.com/atwin140/ahead-dastor.git` |
| Default StorageClass | `synology-iscsi-storage` |

Both selected CSVs were verified as current channel versions in DaSTOR's live catalog. This verifies availability, not successful installation or Red Hat's full support matrix. The live Dev Spaces catalog example supplied the `org.eclipse.che/v2` CheCluster structure used here. Neither operator had an existing subscription when inspected.

## Repository layout

The root `devfile.yaml` defines Andrew's generic tooling workspace and clones this
`ahead-dastor` repository. It preserves the supplied tooling image, resource
requests/limits, per-workspace storage, `HOME=/projects`, and `hostUsers: true`.
Commit it at the repository root, then use the repository URL when creating a
workspace in Dev Spaces. It is a workspace definition, not an Argo CD resource;
do not add it to either Kustomization. Image startup and workspace creation have
not been tested.

Copy the **contents** of this folder to the repository root, preserving these paths:

```text
argocd/
  devspaces-operator.yaml
  devspaces-instance.yaml
components/devspaces/
  operator/
    kustomization.yaml
    devworkspace-subscription.yaml
    devspaces-subscription.yaml
  instance/
    kustomization.yaml
    namespace.yaml
    checluster.yaml
```

Application manifests use the existing repository URL, `HEAD`, the existing `platform-services` project, and the local DaSTOR cluster destination. Adjust `targetRevision` if you deploy from a particular branch/tag/commit. If you place the files elsewhere, update both Application source paths. Merge the Application manifests into your existing app-of-apps/bootstrap configuration using its existing conventions; merely committing these files does not necessarily register the Applications. Do not point a recursive Argo CD application at this entire delivery folder.

The existing `openshift-operators` namespace and `global-operators` OperatorGroup are reused. Do not create another OperatorGroup there. The existing Argo CD project permits these resource kinds, destinations, and this repository. The Argo CD controller still needs Kubernetes RBAC permission to manage Subscriptions in `openshift-operators`, create the instance namespace, and manage CheClusters in it. Project permissions do not grant Kubernetes RBAC. Confirm these permissions through your existing GitOps administration process; this bundle does not grant cluster-admin or modify shared operator-namespace labels.

## Deployment sequence for the repository owner

1. Commit the files and register both Application manifests through your normal GitOps bootstrap workflow. Both Applications have automatic sync disabled.
2. In Argo CD, manually sync **dastor-devspaces-operator**. This creates both Subscriptions. It does not approve their InstallPlans.
3. In the OpenShift console, inspect the pending InstallPlan(s) in `openshift-operators`. Check that the plan includes `devspacesoperator.v3.30.1` and `devworkspace-operator.v0.43.0` as appropriate. OLM may combine operators and dependencies in a plan; review every included CSV, including any unrelated changes in this shared namespace. Approve only the reviewed plan(s).
4. Wait for both operator CSVs to reach **Succeeded** and the `checlusters.org.eclipse.che` CRD to be established. An Argo CD operator Application being Synced alone does not establish operator readiness.
5. Manually sync **dastor-devspaces**. This creates the namespace and CheCluster. Syncing before the CRD exists will fail; retry after the operator is ready. The separate Applications intentionally make this a human-controlled installation sequence.
6. Verify the CheCluster becomes Available, open its reported URL, and test a workspace including persistent storage. Authentication and route configuration use operator defaults and the cluster's existing OpenShift identity/ingress configuration.

The CheCluster uses operator defaults, including the cluster's default StorageClass. `synology-iscsi-storage` was the only StorageClass and was marked default during inspection. Workspace provisioning, storage behavior, image pulls, identity-provider access, quotas, and ingress were not exercised. Git-provider OAuth integrations and custom certificate settings are not configured in this minimal installation.

## Version control and manual approval

`startingCSV` selects an **initial installation version**, not a permanent version lock or downgrade setting. `installPlanApproval: Manual` prevents initial installation and subsequent OLM upgrades until their InstallPlans are approved. Future catalog updates can produce pending plans even while Git still contains the original `startingCSV`. Changing `startingCSV` is not an upgrade trigger for an already installed operator.

For an upgrade, review the supported upgrade path and all CSVs in the generated plan, update this repository's documented target versions, then approve the appropriate plan through your operational process. Keep both subscriptions on `Manual`. Do not add an auto-approval job or commit generated InstallPlans/CSVs. Argo CD sync approval and OLM InstallPlan approval are separate controls; neither substitutes for the other.

## Local validation only

These commands render files locally without contacting or changing the cluster:

```sh
kubectl kustomize components/devspaces/operator
kubectl kustomize components/devspaces/instance
```

Both directories were rendered successfully during preparation. The Application YAML files were also parsed by a local Kustomize build. No server-side dry run, apply, sync, or deployment test was performed.

Optional read-only checks for your own deployment session:

```sh
oc --kubeconfig ~/dastor-kubeconfig get subscriptions.operators.coreos.com -n openshift-operators
oc --kubeconfig ~/dastor-kubeconfig get installplans -n openshift-operators
oc --kubeconfig ~/dastor-kubeconfig get csv -n openshift-operators
oc --kubeconfig ~/dastor-kubeconfig get crd checlusters.org.eclipse.che
oc --kubeconfig ~/dastor-kubeconfig get checluster devspaces -n openshift-devspaces -o yaml
```

## References

- [OLM: selecting an initial operator version and manual approval](https://olm.operatorframework.io/docs/tasks/install-operator-with-olm/)
- [OLM: Subscription approval behavior](https://olm.operatorframework.io/docs/concepts/crds/subscription/)
- [Argo CD: automated sync policy](https://argo-cd.readthedocs.io/en/release-2.10/user-guide/auto_sync/)

The exact operator versions and CheCluster API/example were taken from DaSTOR's live Red Hat package catalog rather than inferred from older documentation examples.
