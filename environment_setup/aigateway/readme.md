# Kong API Gateway for AI Factory

## Overview

This folder contains the Infrastructure as Code (IaC) and configuration for deploying **Kong Gateway OSS** (open-source) on Azure. Kong acts as an API gateway that routes, secures, and rate-limits traffic to **Azure OpenAI** endpoints that are accessible only via private endpoints inside the AI Factory VNet.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  VNet: vnt-esmlcmn-sdc-dev-001  (172.16.0.0/18)                           │
│  RG:   mrvel-1-esml-common-sdc-dev-007                                     │
│                                                                             │
│  ┌──────────────────────────┐     ┌────────────────────────────────────┐    │
│  │ snet-kong-001            │     │ Private Endpoint                    │    │
│  │ (172.16.50.0/28)         │     │ Azure OpenAI / AI Foundry           │    │
│  │ ┌──────────────────────┐ │     │ aif2x46jfc2e.openai.azure.com      │    │
│  │ │ Kong Gateway (ACI)   │─┼────▶│ (resolved to private IP via DNS)    │    │
│  │ │ - Proxy:  :8000      │ │     └────────────────────────────────────┘    │
│  │ │ - Admin:  :8001      │ │                                               │
│  │ │ - SSL:    :8443      │ │     ┌────────────────────────────────────┐    │
│  │ └──────────────────────┘ │     │ Storage Account (File Share)        │    │
│  └──────────────────────────┘     │ kong.yaml config mounted as volume  │    │
│                                   └────────────────────────────────────┘    │
│  RG: mrvel-1-esml-common-kong-sdc-dev-007                                  │
└─────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ HTTP/HTTPS (VNet internal)
        │ Header: apikey or x-api-key
┌───────┴───────────────┐
│ API Consumers          │
│ (VMs, Apps, Services   │
│  inside VNet or peered)│
└────────────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Compute** | Azure Container Instances (ACI) | Simple, VNet-injectable, cost-effective for a single gateway instance |
| **Kong Mode** | DB-less (declarative) | Config-as-code, no database dependency, GitOps-friendly |
| **Networking** | VNet injection via delegated subnet | Reaches Azure OpenAI private endpoint directly |
| **Config Storage** | Azure File Share mounted as volume | Persistent, updatable without redeploying ACI |
| **Authentication** | Key-auth plugin (Kong) + API key (Azure OpenAI) | Two-layer auth: clients auth to Kong, Kong auths to OpenAI |

---

## File Structure

```
azure-enterprise-scale-ml/environment_setup/aigateway/
├── main.bicep                          # Subscription-level Bicep orchestrator
├── kong.yaml                           # Kong declarative configuration (DB-less)
├── readme.md                           # This file
├── modules/
│   ├── kong-networking.bicep           # Subnet + NSG for Kong ACI
│   ├── kong-storage.bicep              # Storage account + file share for config
│   └── kong-aci.bicep                  # Container Instance running Kong Gateway
└── scripts/
    ├── upload-kong-config.ps1          # Uploads kong.yaml to Azure File Share
    └── restart-kong.ps1                # Restarts Kong ACI after config update
```

### Pipeline Files (outside this folder)

| File | Location | Purpose |
|------|----------|---------|
| `job-2-gw-kong.yaml` | `aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-common/jobs/` | Azure DevOps pipeline job steps |
| `variables.yaml` | `aifactory/esml-infra/azure-devops/bicep/yaml/variables/` | Pipeline variables (Kong section) |

---

## Resources Deployed

| Resource | Type | Resource Group | Purpose |
|----------|------|----------------|---------|
| Resource Group | `Microsoft.Resources/resourceGroups` | `mrvel-1-esml-common-kong-sdc-dev-007` | Dedicated RG for Kong resources |
| NSG | `Microsoft.Network/networkSecurityGroups` | `mrvel-1-esml-common-sdc-dev-007` (VNet RG) | Network security for Kong subnet |
| Subnet | `Microsoft.Network/virtualNetworks/subnets` | `mrvel-1-esml-common-sdc-dev-007` (VNet RG) | Delegated subnet for ACI |
| Storage Account | `Microsoft.Storage/storageAccounts` | `mrvel-1-esml-common-kong-sdc-dev-007` | Hosts Kong config file share |
| File Share | `Microsoft.Storage/storageAccounts/fileServices/shares` | `mrvel-1-esml-common-kong-sdc-dev-007` | `kong-config` share |
| Container Group | `Microsoft.ContainerInstance/containerGroups` | `mrvel-1-esml-common-kong-sdc-dev-007` | Kong Gateway container |

---

## Bicep Modules Explained

### `main.bicep` (Subscription Level)

The orchestrator deployment that creates the resource group and calls all child modules.

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `env` | Yes | - | Environment: `dev`, `test`, `prod` |
| `location` | Yes | - | Azure region |
| `locationSuffix` | Yes | - | Short region suffix (e.g., `sdc`) |
| `aifactorySuffixRG` | Yes | - | AI Factory scale set suffix (e.g., `-007`) |
| `commonRGNamePrefix` | Yes | - | RG name prefix (e.g., `mrvel-1-`) |
| `tags` | Yes | - | Resource tags |
| `vnetResourceGroupName` | Yes | - | Existing VNet resource group |
| `vnetName` | Yes | - | Existing VNet name |
| `kongSubnetCidr` | Yes | - | CIDR for Kong subnet (min `/28`) |
| `azureOpenAIEndpoint` | Yes | - | Azure OpenAI base URL |
| `azureOpenAIApiKey` | Yes | - | Azure OpenAI API key (secure) |
| `kongImage` | No | `kong/kong-gateway:3.9` | Kong container image |
| `kongCpu` | No | `2` | CPU cores |
| `kongMemoryGb` | No | `4` | Memory in GB |
| `userAssignedIdentityId` | No | `""` | User-assigned managed identity resource ID |

### `modules/kong-networking.bicep` (Resource Group Level)

Creates a subnet in the existing VNet, delegated to ACI, with an NSG.

**NSG Rules:**

| Rule | Priority | Direction | Port | Source | Action |
|------|----------|-----------|------|--------|--------|
| Allow-Kong-Proxy-Inbound | 100 | Inbound | 8000 | VNet | Allow |
| Allow-Kong-ProxySSL-Inbound | 110 | Inbound | 8443 | VNet | Allow |
| Allow-Kong-Admin-VNet | 150 | Inbound | 8001 | VNet | Allow |
| Deny-Kong-Admin-External | 200 | Inbound | 8001 | Internet | Deny |
| Allow-HTTPS-Outbound | 100 | Outbound | 443 | Any | Allow (to VNet) |

### `modules/kong-storage.bicep` (Resource Group Level)

Creates a storage account with a file share to hold the Kong declarative config. The storage account:

- Enforces TLS 1.2
- Denies public blob access
- Restricts network access to the Kong subnet only
- Allows Azure services bypass

### `modules/kong-aci.bicep` (Resource Group Level)

Deploys Kong Gateway as an Azure Container Instance:

- **OS**: Linux
- **VNet injection**: Via delegated subnet (private IP only)
- **DB-less mode**: `KONG_DATABASE=off` with declarative config mounted from Azure File Share
- **Health probes**: Liveness and readiness probes on `/status` endpoint
- **Logging**: stdout/stderr for proxy and admin
- **Identity**: Optionally attaches a user-assigned managed identity

---

## Kong Configuration (`kong.yaml`)

Kong runs in **DB-less declarative mode**. The config file defines:

### Services

| Service | URL | Purpose |
|---------|-----|---------|
| `azure-openai-service` | `https://aif2x46jfc2e.openai.azure.com` | General Azure OpenAI API access |
| `azure-openai-chat` | `https://aif2x46jfc2e.openai.azure.com/openai/deployments` | Chat completions shortcut |

### Routes

| Route | Path | Upstream |
|-------|------|----------|
| `azure-openai-route` | `/openai/*` | General OpenAI API (strip path) |
| `azure-openai-chat-route` | `/ai/chat/*` | Chat completions (strip path) |

### Plugins

| Plugin | Scope | Purpose |
|--------|-------|---------|
| `key-auth` | Global | Clients must provide API key (`apikey` or `x-api-key` header) |
| `request-transformer` | Per service | Adds `api-key` header for Azure OpenAI authentication |
| `rate-limiting` | Per service | 60 req/min for general, 30 req/min for chat |
| `request-size-limiting` | Per service | Max 4 MB payload |
| `correlation-id` | Global | Adds `X-Request-ID` for tracing |
| `file-log` | Global | Logs to stdout |

### Request Flow

```
1. Client sends request to Kong (e.g., POST http://<kong-ip>:8000/ai/chat/gpt-4o/chat/completions?api-version=2024-10-21)
   Headers: { "apikey": "<kong-consumer-key>", "Content-Type": "application/json" }

2. Kong key-auth plugin validates the consumer API key

3. Kong request-transformer plugin:
   - Adds "api-key: <azure-openai-key>" header
   - Replaces "Host" header with the Azure OpenAI hostname

4. Kong forwards to: https://aif2x46jfc2e.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21
   (resolved to private IP via private DNS zone in VNet)

5. Response flows back through Kong to the client
```

---

## Pipeline Variables

The following variables are added to `variables.yaml` under the Kong section:

| Variable | Default | Description |
|----------|---------|-------------|
| `enableKongGateway` | `false` | Enable/disable Kong deployment |
| `kong_image` | `kong/kong-gateway:3.9` | Kong Docker image |
| `kong_cpu` | `2` | CPU cores for ACI |
| `kong_memory_gb` | `4` | Memory GB for ACI |
| `kong_subnet_name` | `snet-kong-001` | Subnet name in existing VNet |
| `kong_subnet_cidr` | `172.16.50.0/28` | Subnet CIDR (within VNet /18 range) |
| `kong_azure_openai_endpoint` | `https://aif2x46jfc2e.openai.azure.com` | Azure OpenAI base URL |
| `kong_openai_key_secret_name` | `kong-azure-openai-api-key` | Key Vault secret name for OpenAI key |
| `kong_consumer_key_secret_name` | `kong-consumer-api-key` | Key Vault secret name for consumer key |
| `kong_user_assigned_identity_id` | (full resource ID) | Managed identity for Kong |

---

## Azure DevOps Pipeline Job (`job-2-gw-kong.yaml`)

The pipeline job executes these steps:

| Step | Display Name | Description |
|------|-------------|-------------|
| 0 | `00_kong_print_info` | Prints deployment configuration |
| 1 | `01_kong_fetch_secrets_from_kv` | Fetches Azure OpenAI API key from seeding Key Vault |
| 2 | `02_kong_deploy_bicep` | Deploys Bicep template (RG, subnet, storage, ACI) |
| 3 | `03_kong_upload_config` | Uploads `kong.yaml` (with secrets substituted) to Azure File Share |
| 4 | `04_kong_restart_container` | Restarts Kong ACI to pick up new config |
| 5 | `05_kong_verify_health` | Prints Kong IP, status, and usage examples |

### Prerequisites

Before running the pipeline:

1. **Seeding Key Vault** must contain:
   - `kong-azure-openai-api-key`: The Azure OpenAI API key
   - `kong-consumer-api-key` (optional): Pre-set consumer key, or one will be auto-generated

2. **Service Connection** must have permissions to:
   - Create resource groups in the subscription
   - Create subnets in the existing VNet
   - Deploy ACI, storage accounts
   - Read secrets from the seeding Key Vault

3. **VNet** must exist with available address space for the Kong subnet CIDR

### Integration with Existing Pipeline

To add Kong to the existing AI Factory common pipeline (`infra-aifactory-common.yaml`), add:

```yaml
# In the Dev stage job steps:
- template: ./jobs/job-2-gw-kong.yaml
  parameters:
    serviceConnection: ${{ variables.dev_service_connection }}
    seedingKvServiceConnection: ${{ variables.dev_seeding_kv_service_connection }}
```

---

## Networking Details

### Subnet Allocation

The Kong subnet `172.16.50.0/28` provides 16 IP addresses (14 usable), which is sufficient for a single ACI container group. This range falls within the existing VNet CIDR `172.16.0.0/18` (addresses 172.16.0.0 – 172.16.63.255).

### Private Endpoint Connectivity

Kong reaches Azure OpenAI via the **private DNS zone** linked to the VNet:

```
aif2x46jfc2e.openai.azure.com
  └─> Private DNS Zone: privatelink.openai.azure.com
       └─> A record → Private IP of the OpenAI private endpoint
```

Since Kong's ACI is injected into the same VNet, DNS resolution automatically returns the private IP.

### NSG Design

- **Inbound**: Only VNet traffic can reach Kong (proxy on 8000/8443, admin on 8001)
- **Admin port**: Explicitly denied from Internet (defense in depth)
- **Outbound**: HTTPS (443) to VNet for reaching private endpoints

---

## Security Considerations

| Aspect | Implementation |
|--------|---------------|
| **No public IP** | Kong ACI has private IP only (VNet injection) |
| **Admin API protected** | NSG denies Internet access to port 8001; only VNet access allowed |
| **Secrets management** | API keys fetched from Key Vault; never stored in source code |
| **Client authentication** | Kong `key-auth` plugin requires API key for all requests |
| **Upstream authentication** | `request-transformer` plugin injects Azure OpenAI API key |
| **Credentials hidden** | `hide_credentials: true` strips client API key before forwarding upstream |
| **TLS** | Storage account enforces TLS 1.2; Kong supports SSL on port 8443 |
| **Rate limiting** | Per-service rate limits prevent abuse |
| **Network isolation** | Storage account restricted to Kong subnet only |

---

## Usage Examples

After deployment, Kong is accessible from within the VNet (or peered networks):

### Chat Completions

```bash
curl -X POST http://<kong-private-ip>:8000/ai/chat/gpt-4o/chat/completions?api-version=2024-10-21 \
  -H "Content-Type: application/json" \
  -H "apikey: <your-kong-consumer-key>" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### List Models

```bash
curl http://<kong-private-ip>:8000/openai/openai/models?api-version=2024-10-21 \
  -H "apikey: <your-kong-consumer-key>"
```

### Kong Admin API (from VNet only)

```bash
# Check status
curl http://<kong-private-ip>:8001/status

# List services
curl http://<kong-private-ip>:8001/services

# List routes
curl http://<kong-private-ip>:8001/routes
```

---

## Updating Kong Configuration

To update the Kong routing/plugin configuration:

1. Edit `azure-enterprise-scale-ml/environment_setup/aigateway/kong.yaml`
2. Run the upload script or trigger the pipeline:

```powershell
# Manual upload
.\kong\scripts\upload-kong-config.ps1 `
  -ResourceGroupName "mrvel-1-esml-common-kong-sdc-dev-007" `
  -StorageAccountName "<storage-account-name>" `
  -SubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
  -AzureOpenAIApiKey "<your-openai-key>"

# Restart Kong to pick up changes
.\kong\scripts\restart-kong.ps1 `
  -ResourceGroupName "mrvel-1-esml-common-kong-sdc-dev-007" `
  -SubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4"
```

---

## Troubleshooting

### Kong container not starting

```bash
# Check container logs
az container logs --resource-group mrvel-1-esml-common-kong-sdc-dev-007 --name aci-kong-sdc-dev-001

# Check container status
az container show --resource-group mrvel-1-esml-common-kong-sdc-dev-007 --name aci-kong-sdc-dev-001 --query "instanceView.state"
```

### Kong can't reach Azure OpenAI

1. Verify the private DNS zone `privatelink.openai.azure.com` is linked to the VNet
2. Verify the private endpoint for Azure OpenAI exists and is approved
3. Check NSG outbound rules allow HTTPS (443) to VNet
4. Test DNS resolution from within the VNet

### Config not loaded

1. Verify the file share contains `kong.yaml`
2. Check the storage account network rules allow the Kong subnet
3. Verify the file share is mounted correctly (check container logs)

---

## Cost Estimate (Dev Environment)

| Resource | SKU | Estimated Monthly Cost |
|----------|-----|----------------------|
| ACI (2 vCPU, 4 GB) | Standard Linux | ~$70 |
| Storage Account (1 GB File Share) | Standard LRS | ~$1 |
| NSG | Free | $0 |
| **Total** | | **~$71/month** |

> Costs vary by region. Reduce ACI specs (`kong_cpu`/`kong_memory_gb`) for lighter workloads.
