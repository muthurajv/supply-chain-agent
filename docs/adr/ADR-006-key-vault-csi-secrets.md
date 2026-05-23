# ADR-006: Azure Key Vault CSI driver for secrets injection on AKS

**Date:** 2025-05-22  
**Status:** Accepted

## Context

The application requires five secrets at runtime (OpenAI API key, Cosmos connection
string, Azure Search key, AAD client secret, Grafana API key). These must be
available to pods without ever appearing in source control, ConfigMaps, or
unencrypted K8s Secrets.

Options evaluated:

| Option | Encrypted at rest | No code changes | Auto-rotation | AKS native |
|---|---|---|---|---|
| K8s Secret (plain) | Only with KMS plugin | Yes | No | Yes |
| Azure Key Vault SDK in app | Yes | No (code per secret) | Manual re-fetch | Yes |
| Managed Identity + Key Vault SDK | Yes | No (code per secret) | Manual re-fetch | Yes |
| Key Vault CSI driver (Secrets Store) | Yes (KV-backed) | Yes | Yes (on pod restart) | Yes (AKS add-on) |

The CSI driver is available as a managed AKS add-on (`--enable-secret-rotation`),
requires no application code changes, and syncs secrets into standard K8s Secrets
so the existing `secretRef` in `deployment.yaml` continues to work unchanged.

## Decision

Use the **Azure Key Vault Provider for the Secrets Store CSI Driver** (AKS managed
add-on). The `SecretProviderClass` manifest at `deploy/k8s/secrets-provider.yaml`
declares the five secret mappings. The driver mounts them as a volume and syncs
them into the `supply-chain-agent-secrets` K8s Secret.

The pod identity model is **workload identity** (AAD Workload Identity bound to the
agent pod's service account). The workload identity client ID is passed to the
`SecretProviderClass` via the `clientID` parameter.

## Consequences

- No secrets appear in source control, ConfigMaps, or CI environment variables.
  The `deploy/k8s/secrets-provider.yaml` file contains only Key Vault secret
  *names*, not values.
- Secret rotation in Key Vault propagates to pods on their next restart when
  `--enable-secret-rotation` is active on the AKS add-on.
- Adding a new secret requires: (1) adding it to Key Vault, (2) adding the
  `objectName` entry to `secrets-provider.yaml`, (3) updating the `secretObjects`
  block so the new key is synced into the K8s Secret. No app code changes if the
  secret is consumed via env var.
- The CSI volume mount must be added to `deployment.yaml` (documented as a patch
  comment in `secrets-provider.yaml`). The `SecretProviderClass` sync only
  triggers when at least one pod mounts the CSI volume.
- Local development uses `.env` (never committed). The `.env.example` documents
  all required variables. See §14.
