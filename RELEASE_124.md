# 🎉 Version 1.24 - Release Notes
**Release Tag:** [release_124](https://github.com/jostrm/azure-enterprise-scale-ml/releases/tag/release_124)  
**Release Date:** January 2026

## 📌 Version Configuration

### main.bicep
```bicep
param aifactoryVersionMajor int = 1
param aifactoryVersionMinor int = 24
```

### Azure DevOps - variables.yaml
```yaml
aifactory_version_major: "1" 
aifactory_version_minor: "24" 
```

### GitHub Actions - .env
```bash
AIFACTORY_VERSION_MAJOR="1"
AIFACTORY_VERSION_MINOR="24"
```

---

# 🚀 What's New in v1.24

## 🔒 Security Enhancements

### 🔐 Customer Managed Encryption Keys (CMEK)
**Enterprise-grade encryption at rest for all supported Azure services**

- ✅ **Full CMEK Support** across AI Factory services:
  - 🗄️ Storage Accounts (Blob, File, Queue)
  - 🔑 Key Vault encryption
  - 🤖 Azure AI Services & AI Foundry
  - 🌍 Cosmos DB encryption
  - 📊 SQL Database encryption
  - ⚙️ AKS Disk Encryption Set (DES) for compute nodes
  
- 🎛️ **Simple Configuration** in `variables.yaml`:
  ```yaml
  cmk: "true"                          # Enable CMEK globally
  cmkKeyName: "aifactory-cmk-key"     # Unified key name
  cmkKeyVersion: ""                    # Auto-rotate to latest
  ```

- 🔧 **Requirements Validation:**
  - ✅ Key Vault MUST have `enableSoftDelete=true` and `enablePurgeProtection=true` (e.g. in your seeding keyvault)
  - ✅ Managed identities automatically assigned "Key Vault Crypto Service Encryption User" role
  - ✅ Only RSA and RSA-HSM keys of size 2048 are supported
  - ✅ Trusted Microsoft services bypass automatically configured

### 🛡️ Defender for AI
**Protect your AI workloads with Microsoft Defender**

- 📡 **Two-Level Protection:**
  ```yaml
  enableDefenderforAISubLevel: "false"       # Subscription-level protection
  enableDefenderforAIResourceLevel: "false"  # Per-resource protection
  ```

- 🎯 **Granular Control**: Enable at subscription level for all resources, or per individual resource
- 🔍 **Threat Detection**: Real-time monitoring of AI Services and AI Foundry resources
- 📊 **Security Insights**: Integrated with Microsoft Defender for Cloud

---

## 🤖 AI Services & Platform Updates

### 🏗️ Bot Service Integration
**Native support for conversational AI and bot deployments**

- 💬 **Microsoft Bot Framework** integration
- 🔗 **Seamless AI Foundry connection** for intelligent bot scenarios
- 🌐 **Multi-channel support** (Teams, Web Chat, etc.)
- 📝 Configuration:
  ```yaml
  enableBotService: "true"  # Enable Bot Service
  ```

### 🏠 AI Foundry Capability Host (Private Agents)
**Keep agent execution, history, and data 100% in your subscription**

- 🔒 **Full Data Residency**: Agent threads, history, and metadata stay in YOUR network
- 💾 **Dedicated Infrastructure**: Uses your CosmosDB, Storage, and AI Search
- 🌐 **Network Injection**: Agents run in your vNet with private endpoints
- ⚙️ Configuration:
  ```yaml
  enableAFoundryCaphost: "true"              # Enable capability host
  disableAgentNetworkInjection: "false"     # Keep agents in your network
  ```

- ⚠️ **Network Requirements**:
  - ✅ Requires **Class B or C** networks (`172.16.0.0/12` or `192.168.0.0/16`)
  - ❌ Class A networks not supported (set `disableAgentNetworkInjection: "true"`)
  - 🔧 Container Apps subnet must be delegated to `Microsoft.App/environment`

### 🌉 AI Gateway - BYO API Management (APIM)
**Integrate your existing API Management for AI workload governance**

- 🔗 **Private Endpoint** to your existing APIM instance
- 📊 **Centralized Monitoring**: All AI traffic through your API Gateway
- 🎛️ **Policy Control**: Apply rate limiting, authentication, and custom policies
- 💰 **Cost Tracking**: Unified billing and chargeback through APIM
- 📝 Configuration:
  ```yaml
  foundryApiManagementResourceId: "/subscriptions/.../Microsoft.ApiManagement/service/your-apim"
  ```

---

## 🔍 AI Search Enhancements

### 🔗 Shared Private Link Support
**Secure, direct connections from AI Search to your data sources**

- 📦 **Storage Account Links** (Blob + File):
  - ✅ Private connectivity to blob storage for indexers
  - ✅ File share access for document processing
  - ✅ No public internet exposure required

- 🤖 **AI Foundry/OpenAI Links**:
  - ✅ Direct private connection to AI Services
  - ✅ Secure model inference during indexing
  - ✅ Embedding generation with private endpoints

- 🎛️ **Flexible Deployment**:
  ```yaml
  enableAISearchSharedPrivateLink: "true"   # Enable shared links
  ```

- 🏗️ **Supported Tiers**: Basic and higher (Standard S1+ for AI enrichment/skillsets)
- 🔧 **Auto-Approval**: Bicep automatically approves shared private link requests

---

## 🔄 Reliability & Operations

### ♻️ Automatic Retry Logic
**Intelligent retry mechanism for transient failures**

- 🔄 **Configurable Retry Strategy**:
  ```yaml
  enableRetries: "true"                  # Enable retry logic
  retryMinutes: "5"                     # Wait 5 min between 1st-2nd attempt
  retryMinutesExtended: "15"            # Wait 15 min between 2nd-3rd attempt
  maxRetryAttempts: "2"                 # Total attempts: 1 + 2 retries = 3
  ```

- 🎯 **Smart Backoff**: Exponential delays prevent overwhelming Azure APIs
- 🛠️ **Scenario Coverage**: AI Foundry, AI Services, and complex deployments
- 📊 **Improved Success Rate**: Handles rate limits and service throttling

### 🧹 Auto-Cleanup on Failures
**Automatically clean up failed deployments**

- 🗑️ **Automatic Resource Deletion**: Failed resources auto-delete
- 🧽 **Soft-Delete Purging**: AI Services and AI Foundry soft-deleted resources purged
- ⚙️ Configuration:
  ```yaml
  debugEnableCleaning: "true"   # Enable auto-cleanup
  ```

- 💡 **Use Case**: Great for dev/test environments and iterative deployments

---

## 🎛️ Pipeline & Debugging Improvements

### 📦 Modular Debug Controls
**Disable specific deployment sections for faster iterations**

New granular debug flags in `variables.yaml`:

```yaml
debug_disable_validation_tasks: "false"       # Skip validation tasks
debug_disable_05_build_acr_image: "false"     # Skip ACR image build
debug_disable_61_foundation: "false"          # Skip RG, MI, VM
debug_disable_62_core_infrastructure: "false" # Skip Storage, KV, ACR
debug_disable_63_cognitive_services: "false"  # Skip AI Services
debug_disable_64_databases: "false"           # Skip DB deployment
debug_disable_65_compute_services: "false"    # Skip compute (ACA, WebApp)
debug_disable_66_ai_platform: "false"         # Skip AI Foundry v1 Hub
debug_disable_67_data_ml_platform: "false"    # Skip AML, Databricks, ADF
debug_disable_68_integration: "false"         # Skip Logic Apps, Event Hubs
debug_disable_69_aifoundry_2025: "false"      # Skip AI Foundry v2
debug_disable_100_rbac_security: "false"      # Skip RBAC assignments
debug_disable_10_aifactory_dashboards: "true" # Skip dashboards
```

### ⚡ Deployment Strategies
**Choose your deployment approach**

```yaml
foundryDeploymentType: "1"   # 1=PG-based, 2=AVM-based, 3=Both (fallback)
```

- 🔬 **Type 1 (Default)**: Proven AI Factory Bicep templates
- 📚 **Type 2**: Azure Verified Modules (AVM) for standardization
- 🔄 **Type 3**: Try PG first, fallback to AVM on failure

---

## 🆕 New Azure Service Integrations

### 🔧 Previously Unavailable Services

#### ⚙️ Azure Services Now Supported:
- 🤖 **Bot Service** - Conversational AI integration
- 🔄 **Logic Apps** - Workflow automation and integration
- 📡 **Event Hubs** - Real-time event streaming
- 🐘 **PostgreSQL** - Flexible Server for relational data
- 🗄️ **SQL Database** - Enterprise-grade SQL workloads
- ⚡ **Redis Cache** - In-memory caching for performance

#### 🔍 Cognitive Services:
- 🎯 **Bing Custom Search** - Custom search with grounding (G2 SKU)
- 🔎 **Bing Search** - RETURNED after temporary removal

### 📝 Configuration Examples

```yaml
# Integration Services
enableLogicApps: "false"
enableEventHubs: "false"

# Databases
enablePostgreSQL: "false"
postGresAdminEmails: "admin@example.com"  # Entra ID admin
enableSQLDatabase: "false"
enableRedisCache: "false"

# Cognitive Services
enableBingCustomSearch: "false"
bingCustomSearchSku: "G2"    # Custom search with grounding
enableBing: "false"          # Standard Bing Search
```

---

## 🏗️ Customization: BYO (Bring Your Own)

### 🏷️ BYO Naming Convention
**Override default "esml" naming for brand alignment**

```yaml
projectPrefix: 'acme-'      # Default: 'esml-'
projectSuffix: '-prod'      # Default: '-rg'
```

- 📛 **Before**: `mrvel-1-esml-project001-eus2-dev-001-rg`
- 📛 **After**: `mrvel-1-acme-project001-eus2-dev-001-prod`

### 🏰 BYO App Service Environment (ASEv3)
**Use your centralized, enterprise-grade ASE**

```yaml
byoASEv3: "true"
byoAseFullResourceId: "/subscriptions/.../hostingEnvironments/yourASE"
byoAseAppServicePlanResourceId: "/subscriptions/.../serverfarms/yourPlan"
```

- 💰 **Cost Savings**: Share ASE across projects
- 🔒 **Enhanced Isolation**: Network-isolated compute
- 🎛️ **Centralized Management**: Single ASE for multiple apps

### 🌐 BYO Subnets (Enhanced)
**Specify exact subnets, not just vNets**

```yaml
BYO_subnets: "true"
subnetProjGenAI: "snt-dev-prj<xxx>-genai"       # AI workloads
subnetProjACA: "snt-prj<xxx>-aca"               # Container Apps
subnetProjACA2: "snt-prj<xxx>-aca2"             # Agents (capability host)
subnetProjAKS: "snt-prj<xxx>-aks"               # Kubernetes
subnetProjDatabricksPublic: "snt-prj001-dbxpub"
subnetProjDatabricksPrivate: "snt-prj<xxx>-dbxpriv"
```

- 🎯 **Precise Control**: Full subnet specification
- 🔧 **Flexible Naming**: Use `<xxx>` for project number replacement
- 🌍 **Environment-Specific**: Different subnets per env (dev/test/prod)

---

## 🐛 Bug Fixes

### ✅ Data Factory Private Access
- **Issue**: Data Factory private endpoints not fully configured
- **Fixed**: Complete private networking now working correctly
- **Impact**: Fully isolated data pipelines without public access

### ✅ Container Registry Networking
- **Enhanced**: Better IP whitelisting for ACR
- **New**: Admin user toggle for security compliance
- **Configuration**:
  ```yaml
  acr_adminUserEnabled: "false"  # Disable admin for security
  acr_IP_whitelist: "10.0.0.1,10.0.0.2/24"  # Selected networks
  ```

---

## 📦 Enhanced Service Properties

### 🐳 Azure Container Registry (ACR)
```yaml
acr_adminUserEnabled: "false"         # Security: disable admin user
acr_IP_whitelist: "1.2.3.4,5.6.7.0/24"  # Network: IP whitelist
acr_SKU: "Premium"                    # Required for private endpoints
acr_dedicated: "true"                 # Premium features
```

### 🤖 AI Foundry V2 Configuration
```yaml
enableAIFoundry: "true"
updateAIFoundry: "false"                                    # Update existing
addAIFoundry: "false"                                       # Create new instance
enableAFoundryCaphost: "true"                              # Private agents
enableAIFactoryCreatedDefaultProjectForAIFv2: "true"       # Auto-create project
disableAgentNetworkInjection: "false"                      # Keep in vNet
foundryDeploymentType: "1"                                  # Deployment strategy
```

### ⚙️ Azure Kubernetes Service (AKS)
```yaml
admin_aks_version_override: "1.33.2"   # Latest stable (2025-09)
```

- ✅ **Multi-Region Available**: EUS2, SDC, WEU
- 🔄 **Auto-Upgrade Support**: Patch version updates
- 🔒 **Enhanced Security**: Network policy support

---

## 🎯 Improved User Experience

### 🤖 "No Touch" Variables
**Variables that manage themselves**

1. **`aifactory_salt_random`**: Auto-generated unique suffix
   - ✅ No manual intervention needed
   - ✅ Deterministic from Managed Identity
   
2. **`runNetworkingVar`**: Smart subnet creation
   - ✅ Can stay `"true"` permanently
   - ✅ "Create if not exists" logic
   - ✅ Safe to re-run pipeline

### ♻️ Pipeline Idempotency
**Run your pipeline 1-N times without issues**

- ✅ **Create If Not Exists**: Resources not duplicated
- ✅ **Smart Detection**: Existing resources reused
- ✅ **Safe Updates**: Only change what needs changing
- 🔄 **Retry-Friendly**: Works with automatic retry logic

### 🏷️ Smart Tagging System
**Automatic metadata propagation**

```yaml
tag_costcenter: "1234"                  # Set once
tagsProject: '{"CostCenter":"$(tag_costcenter)",...}'  # Auto-populated
```

- 📊 **Cost Center Tracking**: Automatic chargeback
- 🏗️ **Architecture Metadata**: Network mode, services, etc.
- 🔄 **Version Tracking**: AI Factory version auto-tagged
- 👥 **Ownership**: Project owners and teams

---

## 📊 Governance & Monitoring

### 📈 New Dashboards
- 🐳 **Container Apps Performance**: Per-project monitoring
- 💰 **Cost Analysis Dashboard**: Automated with shortcuts
- 📊 **Cross-Charge Reporting**: Per project, per environment

### 💾 Cost Control Exports
- 📄 **CSV Reports**: Exported to common storage account
- 💰 **Project-Level**: Individual cost breakdown
- 🌍 **Environment-Level**: Dev/Test/Prod separation
- 📧 **Future**: Email delivery with Excel attachments (Logic Apps integration)

---

## ⚠️ Known Limitations

### 🌐 Network Restrictions for AI Agents
- 📍 **Class A Limitation**: 
  - ❌ Class A networks (`10.0.0.0/8`) do NOT support AI Foundry agent network injection
  - ✅ Class B (`172.16.0.0/12`) and Class C (`192.168.0.0/16`) SUPPORTED
  - 🔧 **Workaround**: Set `disableAgentNetworkInjection: "true"`

- 🚨 **Impact of Disabled Injection**:
  - ❌ "Agent evaluation" after prompts will fail
  - ❌ Azure Blob Storage with File Search tool not supported
  - ⚡ Agents run on Microsoft's network (can't reach private vNet)

### 📧 Pending Features
- 📧 **Email Reporting**: Cross-charge email not yet implemented
- 🔮 **Planned**: Logic Apps integration for automated email delivery

---

## 🗺️ Roadmap Preview

### 🔄 Upcoming in v1.25
- 🎯 **GitHub Actions Parity**: Sync with Azure DevOps features
- 📊 **Enhanced Dashboards**: Refined cost control and project views
- 👥 **Persona Re-enablement**: Advanced RBAC persona features
- 📧 **Email Integration**: Logic Apps-based reporting
- 🔐 **Enhanced Security**: Additional compliance features

---

## 🔄 Migration from v1.23

### ✅ Breaking Changes
**None** - v1.24 is fully backward compatible

### 📝 Recommended Actions

1. **Review CMK Requirements**:
   - If enabling CMEK, ensure Key Vault has purge protection
   - Verify RSA 2048-bit keys are available

2. **Update Variables**:
   ```yaml
   aifactory_version_minor: "24"
   ```

3. **Enable New Features** (optional):
   ```yaml
   enableBotService: "true"
   cmk: "true"
   enableAFoundryCaphost: "true"
   enableRetries: "true"
   ```

---

## 📚 Additional Resources

- 📖 [Full Documentation](https://github.com/jostrm/azure-enterprise-scale-ml)
- 🐛 [Report Issues](https://github.com/jostrm/azure-enterprise-scale-ml/issues)
- 💬 [Discussions](https://github.com/jostrm/azure-enterprise-scale-ml/discussions)
- 🔐 [Security Policy](SECURITY.md)

---

**🎉 Thank you for using AI Factory v1.24!**