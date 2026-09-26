Here’s a simple README.md you can use:

# Sealed Secrets Quick Reference

This guide provides basic Sealed Secrets commands for GitOps workflows and notes for moving Sealed Secrets support to a new cluster.

---

## What Sealed Secrets Does

Sealed Secrets lets you safely store encrypted Kubernetes secrets in Git.

Typical workflow:

1. Create a normal Kubernetes Secret locally
2. Seal it with `kubeseal`
3. Commit only the `SealedSecret` YAML to Git
4. Argo CD applies it
5. The Sealed Secrets controller decrypts it and creates the real Secret in the cluster

> Do not commit unsealed Secret manifests to Git.

---

## Prerequisites

- `oc`
- `kubeseal`
- A running Sealed Secrets controller in the target cluster
- Access to the controller public certificate

---

## Fetch the Sealed Secrets Certificate

```bash
kubeseal --fetch-cert \
  --controller-name sealed-secrets-controller \
  --controller-namespace sealed-secrets \
  > sealed-secrets-cert.pem
```

Create a Kubernetes Secret
From literals
```
oc create secret generic my-secret \
  --from-literal=username=admin \
  --from-literal=password='SuperSecret123' \
  --dry-run=client -o yaml > my-secret.yaml
```
From a file
```
oc create secret generic my-secret \
  --from-file=values.yaml=./values.yaml \
  --dry-run=client -o yaml > my-secret.yaml
```

Seal a Secret
```
kubeseal \
  --format yaml \
  --cert sealed-secrets-cert.pem \
  < clustertest-cluster-registration-secret.yaml > clustertest-cluster-registration-secret-sealed.yaml
```

```
oc apply -f clusterReg-cluster-registration-secret.yaml -n stackrox --dry-run=client -o yaml | kubeseal --format yaml --cert sealed-secrets-cert.pem  > clustertest-cluster-registration-secret-sealed.yaml 
```

Create and seal in one command
```
oc create secret generic my-secret \
  --from-literal=username=admin \
  --from-literal=password='SuperSecret123' \
  --dry-run=client -o yaml | \
kubeseal \
  --format yaml \
  --cert sealed-secrets-cert.pem \
  > my-sealedsecret.yaml
```

Apply the SealedSecret
```
oc apply -f my-sealedsecret.yaml
```

⸻

## Verify Resources

### Check SealedSecrets
```
oc get sealedsecrets -A
```
### Check one SealedSecret
```
oc get sealedsecret my-secret -n my-namespace -o yaml
```
### Check the generated Kubernetes Secret
```
oc get secret my-secret -n my-namespace
```

## Secret Scopes

Namespace-wide scope
```
kubeseal --scope namespace-wide --format yaml \
  --cert sealed-secrets-cert.pem \
  < my-secret.yaml > my-sealedsecret.yaml
```
Cluster-wide scope
```
kubeseal --scope cluster-wide --format yaml \
  --cert sealed-secrets-cert.pem \
  < my-secret.yaml > my-sealedsecret.yaml
```

⸻

# Example GitOps Workflow
```
oc create secret generic github-token \
  --from-literal=token='ghp_xxxxx' \
  --dry-run=client -o yaml | \
kubeseal --format yaml --cert public-cert.pem \
  > github-token-sealed.yaml

git add github-token-sealed.yaml
git commit -m "Add sealed GitHub token"
git push
```


⸻

## Check the Controller
```
oc get pods -n sealed-secrets | grep sealed-secrets
oc logs -n sealed-secrets deploy/sealed-secrets
```

⸻

## Moving Sealed Secrets to a New Cluster

If you want existing SealedSecret objects to continue working on a new cluster, the new cluster must use the same Sealed Secrets private key.

Important

kubeseal --fetch-cert only gets the public certificate.
That helps encrypt secrets, but it does not transfer the ability to decrypt them.

To make old sealed secrets work in a new cluster, you must move the controller keypair.

⸻

Option 1: Export and Restore the Existing Key

On the old cluster, find the key secret
```
oc -n sealed-secrets get secrets
```
Export the key secret
```
oc -n sealed-secrets get secret <sealed-secrets-key-secret> -o yaml > sealed-secrets-key.yaml
```
Clean the exported YAML before reusing it

Remove fields such as:
  -	resourceVersion
  -	uid
  - creationTimestamp
	-	managedFields

Keep:
	-	name
	-	namespace
	-	data
	-	type

Apply it to the new cluster
```
oc apply -f sealed-secrets-key.yaml
```
Restart the Sealed Secrets controller
```
oc -n sealed-secrets delete pod -l name=sealed-secrets-controller
```

⸻

Option 2: Bring Your Own Certificate/Key

You can generate your own keypair and use it in multiple clusters.

Generate a certificate and key
```
openssl req -x509 -days 365 -nodes -newkey rsa:4096 \
  -keyout mytls.key \
  -out mytls.crt \
  -subj "/CN=sealed-secret/O=sealed-secret"
```
Create the TLS secret in the cluster
```
oc -n sealed-secrets create secret tls mycustomkeys \
  --cert=mytls.crt \
  --key=mytls.key
```
Mark it as the active Sealed Secrets key
```
oc -n sealed-secrets label secret mycustomkeys \
  sealedsecrets.bitnami.com/sealed-secrets-key=active
```
Restart the controller
```
oc -n sealed-secrets delete pod -l name=sealed-secrets-controller
```

Recommendations
	-	Use the same key across clusters only if you want the same sealed secrets to work everywhere
	-	Use separate keys per cluster for stronger isolation
	-	Reseal secrets per cluster if you want better security separation

⸻

Best Practices
	-	Never commit unsealed secrets to Git
	-	Commit only SealedSecret manifests
	-	Make sure the certificate used by kubeseal matches the target cluster
	-	Back up your Sealed Secrets key if you need migration or disaster recovery
	-	Use GitOps to manage the sealed manifests, not the decrypted secrets directly
