# MinIO for ACM Multicluster Observability

This component deploys MinIO on the hub cluster and configures the `thanos-object-storage` secret used by ACM MultiClusterObservability.

## What it creates

- Namespace `minio`
- PersistentVolumeClaim `minio-data`
- Deployment `minio`
- Service `minio`
- Route `minio-console`
- Secret `minio-credentials`
- Secret `thanos-object-storage`
- Job `minio-create-observability-bucket`

## Defaults

- Bucket: `observability-thanos`
- Internal endpoint: `minio.minio.svc.cluster.local:9000`
- Hub storage class: `synology-iscsi-storage`
- Images: `quay.io/minio/minio:latest` and `quay.io/minio/mc:latest`

## Required follow-up

Replace the placeholder credentials before production use and regenerate:

- `base/minio-credentials-sealed.yaml`
- `base/thanos-object-storage-sealed.yaml`