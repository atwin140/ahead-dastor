# ahead-dastor

Core OpenShift GitOps configuration for the Dastor cluster.

## Layout

- `bootstrap/` seeds Argo CD with the cluster-discovery ApplicationSet and its AppProjects.
- `components/openshift-gitops/base/` declares the OpenShift GitOps operator subscription and its default Argo CD instance.
- `clusters/dastor/apps/` composes the applications for Dastor and patches their destination.
- `groups/` contains reusable Argo CD application bundles. `groups/all` currently contains cert-manager; `groups/ILG` and `groups/RDG` are empty bundles ready for group-specific applications.
- `components/cert-manager/` installs the OpenShift cert-manager operator and configures the Dastor wildcard certificate.

These `groups/` are GitOps application bundles, not OpenShift user groups or ACM cluster sets. Add a group bundle to a cluster's `apps/kustomization.yaml` only when that cluster should receive its applications.

## Bootstrap

Prerequisites:

- An initial OpenShift GitOps installation is available on the hub to apply the bootstrap manifests.
- Dastor is registered in Argo CD through the cluster-proxy addon.
- Argo CD has access to `git@github.com:atwin140/ahead-dastor.git`.
- The `cloudflare-api-token-secret` Secret exists in Dastor's `cert-manager` namespace with key `api-token`. Keep this credential out of Git.

Apply once to the hub:

```sh
oc apply -k bootstrap/
```

Bootstrap creates an Argo CD Application pointing to `components/openshift-gitops/base/`; Argo then manages the operator subscription and the `openshift-gitops` Argo CD instance. The component sync retries while OLM installs the operator CRDs. The ApplicationSet discovers `clusters/dastor` and generates its cluster configuration Application. The Dastor app bundle then creates the cert-manager child Application targeting the Dastor cluster.

## Certificate setup

The cert-manager Dastor overlay includes the CertManager controller configuration that forces DNS-01 propagation checks through public recursive resolvers (`1.1.1.1:53` and `8.8.8.8:53`). Sync waves install the operator subscription before applying this custom resource. Argo CD retries failed syncs while the operator establishes its CRDs.

Verify on Dastor:

```sh
oc --kubeconfig ~/dastor-kubeconfig get certificate cluster-wildcard -n openshift-ingress
oc --kubeconfig ~/dastor-kubeconfig get secret cluster-wildcard-tls -n openshift-ingress
```