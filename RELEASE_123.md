# Version 1.23 aka 123
[See Release Notes](https://github.com/jostrm/azure-enterprise-scale-ml/releases/tag/release_123)

## main.bicep
- param aifactoryVersionMajor int = 1
- param aifactoryVersionMinor int = 23

## Azure Devops - variables.yaml
```yaml
- aifactory_version_major: "1" # Major version of AI Factory. Used to determine which bicep files to use. 1, 2, etc.
- aifactory_version_minor: "23" # # 2025-05-23: 120_LTS
```

## Github - .env
```bash
- AIFACTORY_VERSION_MAJOR="1"
- AIFACTORY_VERSION_MINOR="23" # 2025-05-23: 120_LTS
```

# Prompt
You are my agent to help create release notes. 
You are to compare code, and aggregate the changes as new features.
Feel free to ues emoji's to describe features, bugfixes and new concepts.

Compare the code branch with release tag release_120, https://github.com/jostrm/azure-enterprise-scale-ml/releases/tag/release_120,  with current branch.
Compare the parts such as: 
- Azure devops pipeline, and its steps
- The Variables.yaml file
- Variables beginnning with "enable...", or "serviceSetting..." is new Azure services that a user can enable or disable to their architecture
- Sections you may have includes: New Features, New Services, Bug fixes, New Concepts, New Customizations: BYO

# AI Release Notes Analysis - 1.20 VS 1.23

Based on comparing release_120 with the current v1.23 branch, here's a comprehensive analysis of the major changes and new features:

## 🚀 **Revolutionary Changes: Unified Architecture**
The most significant change is the **merger of ESML and GenAI projects** into a single, unified GenAI project type. This represents a fundamental shift in the AI Factory architecture, eliminating the need for separate project types and creating a single, comprehensive solution.

Another comprehensive change, is the removal of the PARAMETER folder with multiple .json files. All configuraiton are now in the Varaibles.yaml (.env file for Github) - makes it much easier governance wise to detect new variables, when new features arrives.

## 🎯 **New Modular Service Architecture**
**24 Azure Services** can now be individually enabled/disabled via simple `enable*` flags in variables.yaml:

### 🤖 **AI & ML Services**
- `enableAIServices` - Standalone AI Services with Azure OpenAI endpoints 🔥
- `enableAIFoundryHub` - AI Foundry Hub (legacy v1) 
- `enableAIFoundryV21` - **NEW** AI Foundry v2 (GA enterprise-grade) 🆕
- `enableAFoundryCaphost` - **NEW** Capability host for agents (private network) 🔒
- `enableAzureMachineLearning` - Azure ML v2 
- `enableDatabricks` - Azure Databricks
- `enableDatafactory` - Azure Data Factory with **fixed private access** 🐛➡️✅

### 🧠 **Cognitive Services** 
- `enableAISearch` - Azure AI Search with configurable tiers
- `enableAzureOpenAI` - Standalone Azure OpenAI 
- `enableAzureAIVision` - Computer Vision services
- `enableAzureSpeech` - Speech services
- `enableAIDocIntelligence` - Document Intelligence
- `enableBing` - **RETURNED** Bing Search 🔄
- `enableBingCustomSearch` - **NEW** Bing Custom Search with grounding 🆕

### 💾 **Database Services**
- `enableCosmosDB` - CosmosDB (required for AI Foundry v2 agents)
- `enablePostgreSQL` - PostgreSQL Flexible Servers **NEW** 🆕
- `enableSQLDatabase` - Azure SQL Database **NEW** 🆕  
- `enableRedisCache` - Redis Cache **NEW** 🆕

### 🌐 **Compute & Web Services**
- `enableContainerApps` - Container Apps with environments
- `enableWebApp` - Azure Web Apps
- `enableFunction` - Azure Functions
- `enableLogicApps` - **NEW** Logic Apps 🆕
- `enableEventHubs` - **NEW** Event Hubs 🆕

## 🛠️ **DevOps & Pipeline Enhancements**

### 🔄 **Idempotency & "Create If Not Exists"**
- **No-touch variables**: `aifactory_salt_random` auto-generated 🤖
- **Smart networking**: `runNetworkingVar` can stay true - creates subnets only if needed
- **Re-runnable pipelines**: Run 1-N times without conflicts ♻️

### 🐛 **Advanced Debugging & Error Handling**
**Modular debugging** with granular section control:
- `debug_disable_61_foundation` - Resource groups, identities, VMs
- `debug_disable_62_core_infrastructure` - Storage, KeyVault, ACR
- `debug_disable_63_cognitive_services` - AI services
- `debug_disable_64_databases` - Database services  
- `debug_disable_65_compute_services` - Compute platforms
- `debug_disable_66_ai_platform` - AI Foundry v1
- `debug_disable_67_ml_platform` - ML services
- `debug_disable_69_aifoundry_2025` - **NEW** AI Foundry v2 🆕

**Auto-cleanup on failures**:
- `debugEnableCleaning` - Automatically delete/purge failed resources
- `enableRetries` - **NEW** Automatic retry logic with configurable intervals 🆕

## 🏗️ **Advanced Customization: "Bring Your Own" (BYO)**

### 🆕 **New BYO Capabilities**
1. **BYONamingConvention**: Override default "esml" prefixes via `projectPrefix`/`projectSuffix`
2. **BYOSubnets**: Specify existing subnets instead of just vNets  
3. **BYOAppServiceEnvironment**: Connect to existing ASE v3 via `byoASEv3`
4. **BYOBicep**: Inject custom Bicep templates into pipeline 🔥

### 🔒 **Enhanced Networking**
- **Class B/C network support** for AI Foundry agent injection. Class A via PG contact!
- **Configurable agent network injection**: `disableAgentNetworkInjection`
- **Advanced IP whitelisting** for Container Registry

## 📊 **Governance & Monitoring**

### 📈 **New Dashboards**
- **Per-project Container Apps performance dashboard** 🆕
- **Automated project dashboards** with cost analysis 🆕
- **Cross-charge reporting** with CSV export 🆕

### 🏷️ **Enhanced Tagging**
- **Template-based tagging**: Set `tag_costcenter`, auto-populate metadata
- **Comprehensive project tags** including networking configuration

## 🔧 **Service-Specific Enhancements**

### 🐳 **Container Registry**
- **Admin user control**: `acr_adminUserEnabled`
- **Network whitelisting**: `acr_IP_whitelist` 
- **SKU configuration**: Premium features exposed

### 🤖 **AI Foundry v2 (2025)**
- **Enterprise-grade deployment** with private networking
- **Capability host control** for agent data residency
- **Default project configuration** options
- **RBAC update capabilities**

### ⚙️ **AKS Updates**
- **Version bump**: Default to 1.33.2 (latest stable 2025-09)
- **Multi-region availability** ensured

## 🚨 **Known Limitations**
- **Class A network restriction**: AI Foundry agent injection requires Class B/C networks
- **Agent evaluation limitations** when network injection disabled
- **Email reporting**: Not yet implemented (future LogicApps integration)

## 🔄 **Migration Path**
The unified architecture means existing ESML projects can now leverage all GenAI capabilities by simply enabling the desired services via feature flags, providing a smooth migration path to the enhanced v1.23 capabilities.

# ---- Manual Release Notes: v1.20 VS 1.23 ---- 

# 🎯 **New Concepts**

## 🔄 **Unified Architecture Revolution**
**ESML + GenAI projects are now merged!** 🎉 GenAI project is the host - the only project type you need now.

✅ **Benefits:**
- 🎛️ All services configurable in `Variables.yaml` via `enable...` flags (true/false)
- 🧩 **Deploy services individually**: All except the 3 baseline types (User assigned MI, storage, keyvault) can be deployed individually
- 🚀 **Start small**: Minimalistic deployment to start with, then add services throughout the use case lifecycle
- 🔒 **24 Services** automatically setup with private networking, EntraID access only, and default diagnostic settings

## 🛠️ **All Available Services by Category**

### 🤖 **AI Foundry 2023-2025+**
- `enableAIServices: "true"` ⚡
- `enableAIFoundryHub: "true"` 🏭
- `addAIFoundryHub: "false"` ➕

### 🆕 **AI Foundry 2025 (NEW!)**
- `enableAIFoundryV21: "true"` 🌟
- `updateAIFoundryV21: "true"` 🔄
- `addAIFoundryV21: "false"` ➕
- `enableAFoundryCaphost: "false"` 🏠
- `enableAIFactoryCreatedDefaultProjectForAIFv2: "true"` 🏗️
- `disableAgentNetworkInjection: "true"` 🔒

### 📊 **Data & Machine Learning**
- `enableDatafactory: "false"` 🏭
- `enableAzureMachineLearning: "false"` 🤖
- `addAzureMachineLearning: "false"` ➕
- `enableDatabricks: "false"` 📈

### 🧠 **Cognitive Services**
- `enableAISearch: "true"` 🔍
- `enableAzureOpenAI: "false"` 🤖
- `enableAzureAIVision: "false"` 👁️
- `enableAzureSpeech: "false"` 🗣️
- `enableAIDocIntelligence: "false"` 📄
- `enableBing: "false"` 🔍
- `enableBingCustomSearch: "false"` 🎯
- `bingCustomSearchSku: "G2"` ⚙️

### 💾 **Databases**
- `enableCosmosDB: "false"` 🌍
- `cosmosKind: "GlobalDocumentDB"` 📄
- `enablePostgreSQL: "false"` 🐘
- `postGresAdminEmails: "email_address_only"` 📧
- `enableRedisCache: "false"` ⚡
- `enableSQLDatabase: "false"` 🗄️

### 🌐 **WebApp Services**
- `enableFunction: "false"` ⚡
- `functionRuntime: "dotnet"` 💻
- `functionVersion: "v7.0"` 🔢

### 🔧 **Azure Function Services**
- `enableWebApp: "false"` 🌐
- `webAppRuntime: "python"` 🐍
- `webAppRuntimeVersion: "3.11"` 🔢
- `aseSku: "IsolatedV2"` 🏰
- `aseSkuCode: "I1v2"` 🏷️
- `aseSkuWorkers: 1` 👷

### 📦 **Container Apps**
- `enableContainerApps: "false"` 📦
- `enableAppInsightsDashboard: "false"` 📊
- `aca_w_registry_image: "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"` 🖼️

### 🔗 **Integration Services**
- `enableLogicApps: "false"` 🔄
- `enableEventHubs: "false"` 📡

---

# ✨ **New Features**

- 🤖 **"No touch" variable**: `aifactory_salt_random` is now automatically set
- 🔄 **"No touch" variable**: `runNetworkingVar` can stay `true` all the time, thanks to "create if not exists" logic
- 🏷️ **Smart tagging**: The `tagsProject` variable template takes other variables like `tag_costcenter`
  - 💡 **HowTo**: Set only `tag_costcenter`, and other meta-data tags from AIFactory follow automatically
- 🌐 **Auto-subnet creation**: When you enable a service needing its own subnet, it checks if subnet exists, otherwise creates it
- 🔒 **Auto-DNS zone creation**: Only if you run AI Factory standalone, without centralized private DNS zones
- 🖼️ **Auto-container image**: Creates default image for container apps automatically instead of manual creation
- ♻️ **Pipeline idempotency**: "Create if not exists" - Run pipeline 1-M times without issues

---

# 📊 **Governance & Monitoring**

- 📈 **New Dashboard**: Per project ContainerApps performance dashboard
- 📊 **New Dashboard**: Per project automated dashboard with cost analysis & shortcuts
- 💰 **New Report**: Per AI Factory cost control, per project, per environment
  - 📋 Exported as `.csv` to common storage account
  - 📧 **Optional**: Send as email with Excel attached to project owner

---

# 🛠️ **More Modular - Easier to DEBUG & QUICKER to RUN**

🔧 **Debug Controls**: Disable full sections in `Variables.yaml` for debugging:

- `debug_disable_05_build_acr_image: "false"` 🏗️
- `debug_disable_61_foundation: "false"` 🏗️
- `debug_disable_62_core_infrastructure: "false"` 💾
- `debug_disable_63_cognitive_services: "false"` 🧠
- `debug_disable_64_databases: "false"` 💾
- `debug_disable_65_compute_services: "false"` ⚡
- `debug_disable_66_ai_platform: "false"` 🤖
- `debug_disable_67_ml_platform: "false"` 📊
- `debug_disable_68_integration: "true"` 🔗
- `debug_disable_69_aifoundry_2025: "false"` 🆕
- `debug_disable_100_rbac_security: "false"` 🔒
- `debug_disable_10_aifactory_dashboards: "true"` 📊

🧹 **Auto-cleanup**: Enable cleaning if pipeline fails on Azure ML or AI Foundry:
- `debugEnableCleaning: "false"` - Set to `true` to auto-delete/purge failed resources

---

# 🆕 **New Azure Services in GenAI Project Type**

All services can be enabled/disabled in `variables.yaml` and added incrementally:

- 🌟 **Azure AI Foundry "v2"**: Enterprise-grade AI Foundry project (plus legacy v1 Hub-based)
- 🔄 **Azure Logic Apps** 
- 🏭 **Azure Data Factory**
- 🤖 **Azure Machine Learning**
- 📈 **Azure Databricks**
- 📡 **Azure Event Hubs**
- 🎯 **Bing Custom Search** (NEW!)
- 🔍 **Bing Search** (RETURNED!)

---

# ⚙️ **New Azure Services Properties Exposed**

### 🐳 **Container Registry**
- ✅ Enable/Disable Admin user
- 🌐 IP selected network whitelisting (needed for ContainerApps use cases)
- 💎 Dedicated SKU properties (easy access instead of editing ADO pipeline)

### 🤖 **AI Foundry v2**
- 🏠 **Enable Capability host**: `true`/`false` (default: `true`)
- 🏗️ **Enable default created project**: `true`/`false` (default: `true`)
- 🔒 **disableNetworkInjection**: `true`/`false` (default: `true`)

### ⚙️ **AKS**
- 🔄 **Default version updated**: `1.33.2` (latest stable 2025-09, multi-region available)

---

# 🐛 **Bug Fixes**

1. ✅ **Data Factory private access** is now fixed

---

# 🏗️ **New Customizations: "Bring Your Own" (BYO)**

1. 🏰 **BYOAse**: Use your existing, centralized App Service Environment for Azure WebApp/Function
   - 💡 **HowTo**: Pass resourceID in `variables.yaml`

2. 🏷️ **BYONamingConvention**: Override the "esml" and suffix on project resource groups
   - 💡 **HowTo**: Override `projectPrefix` and `projectSuffix` in `variables.yaml`

3. 🌐 **BYOSubnets**: Specify subnets instead of just vNets in `variables.yaml`
   - 💡 **HowTo**: Inject existing subnets via `variables.yaml`

4. 🧱 **BYOBicep**: Bring your own BICEP and attach to pipeline
   - 💡 **Benefits**: Reuse RBAC model & networking with custom steps

---

# 🗺️ **Roadmap**

- 🔄 **Sync GitHub Actions** with Azure DevOps changes
- 📊 **Dashboards & Reporting**:
  - 💰 Refined cross-charge reports
  - 📈 Refine project dashboard
- 👥 **Personas**: Re-enable features

---

# ⚠️ **Known Limitations & Issues**

- 🌐 **Network Restrictions**: Only Class B and C networks allow AI Foundry vNet injection with own Capability host
  - 🚨 **Impact**: If you have Class A vNet, set `disableAgentNetworkInjection=true`
  - ❌ **Consequence**: "Agent evaluation" after prompts will error out
  - 🔍 **Reason**: AI Foundry managed Agents run on Microsoft's network and can't reach your private vNet/Subnet

- 📧 **Email Feature**: Cross-charging report email not implemented yet (future LogicApps integration)

