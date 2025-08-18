# Bicep Deployment Split Strategy

## Current Situation
- **File**: `32-main.bicep`
- **Size**: 3,492 lines
- **Modules**: 80+ modules deployed in single template
- **Issue**: Complex dependencies, long deployment times, difficult maintenance

## Proposed Split Strategy

### 1. Foundation Deployment (`01-foundation.bicep`)
**Purpose**: Core infrastructure and foundational services
**Dependencies**: None (first deployment)
**Estimated Lines**: ~800

**Components:**
- Resource Group creation
- Private DNS zones setup
- Virtual Machine and Bastion permissions
- Managed Identities (Project & ACA)
- Service Principals and MI arrays
- Debug module
- Key networking components

**Key Modules:**
- `createNewPrivateDnsZonesIfNotExists`
- `projectResourceGroup`
- `miForPrj`
- `miForAca`
- `spAndMI2Array`
- `vmAdminLoginPermissions`
- `debug`

### 2. Cognitive Services Deployment (`02-cognitive-services.bicep`)
**Purpose**: All AI/ML cognitive services
**Dependencies**: Foundation deployment
**Estimated Lines**: ~1,000

**Components:**
- Azure OpenAI
- AI Services (Multi-service)
- Content Safety
- Vision Services
- Speech Services
- Document Intelligence
- AI Search
- Bing Search

**Key Modules:**
- `csAzureOpenAI` + `privateDnsAzureOpenAI`
- `aiServices`
- `csContentSafety` + `privateDnsContentSafety`
- `csVision` + `privateDnsVision`
- `csSpeech` + `privateDnsSpeech`
- `csDocIntelligence` + `privateDnsDocInt`
- `aiSearchService` + `privateDnsAiSearchService`
- `bing`

### 3. Core Infrastructure Deployment (`03-core-infrastructure.bicep`)
**Purpose**: Storage, networking, and core services
**Dependencies**: Foundation deployment
**Estimated Lines**: ~800

**Components:**
- Storage Accounts (both 1001 and 2001)
- Container Registry (ACR)
- Key Vault
- Virtual Machine
- Application Insights
- Core networking and private DNS

**Key Modules:**
- `sacc` + `privateDnsStorage`
- `sa4AIsearch` + `privateDnsStorageGenAI`
- `acr` / `acrCommon2` + `privateDnsContainerRegistry`
- `kv1` + `privateDnsKeyVault`
- `vmPrivate`
- `applicationInsightSWC`
- `appinsights`

### 4. Database Services Deployment (`04-databases.bicep`)
**Purpose**: All database services
**Dependencies**: Core Infrastructure deployment
**Estimated Lines**: ~600

**Components:**
- CosmosDB + RBAC
- PostgreSQL + RBAC  
- Redis Cache + RBAC
- SQL Server/Database + RBAC
- All database private DNS zones

**Key Modules:**
- `cosmosdb` + `cosmosdbRbac` + `privateDnsCosmos`
- `postgreSQL` + `postgreSQLRbac` + `privateDnsPostGreSQL`
- `redisCache` + `redisCacheRbac` + `privateDnsRedisCache`
- `sqlServer` + `sqlRbac` + `privateDnsSql`

### 5. Compute Services Deployment (`05-compute-services.bicep`)
**Purpose**: Web apps, functions, and container apps
**Dependencies**: Core Infrastructure deployment
**Estimated Lines**: ~700

**Components:**
- Web Apps + RBAC
- Function Apps + RBAC
- Container Apps Environment
- Container Apps (API & Web)
- Subnet delegations
- All compute private DNS zones

**Key Modules:**
- `subnetDelegationServerFarm`
- `subnetDelegationAca`
- `webapp` + `privateDnsWebapp` + `rbacForWebAppMSI`
- `function` + `privateDnsFunction` + `rbacForFunctionMSI`
- `containerAppsEnv` + `privateDnscontainerAppsEnv`
- `acaApi`
- `acaWebApp`
- `rbacForContainerAppsMI`

### 6. ML Platform Deployment (`06-ml-platform.bicep`)
**Purpose**: Azure ML and AI Foundry Hub
**Dependencies**: Cognitive Services, Core Infrastructure
**Estimated Lines**: ~500

**Components:**
- Azure Machine Learning Workspace
- AI Foundry Hub
- AI Hub Project
- Core ML RBAC

**Key Modules:**
- `amlv2` + `rbacAmlv2`
- `aiFoundry`
- `aiHub`
- `rbacAcrProjectspecific`
- `rbackSPfromDBX2AMLSWC`

### 7. RBAC and Security Deployment (`07-rbac-security.bicep`)
**Purpose**: All role-based access control and security
**Dependencies**: All previous deployments
**Estimated Lines**: ~600

**Components:**
- Key Vault access policies
- All AI service RBAC
- User permissions
- External service access
- Lake RBAC
- Bastion access

**Key Modules:**
- `addSecret`
- `kvPrjAccessPolicyTechnicalContactAll`
- `kvCommonAccessPolicyGetList`
- `spCommonKeyvaultPolicyGetList`
- `rbacForOpenAI`
- `rbacModuleAIServices`
- `rbacModuleAISearch`
- `rbacModuleUsers`
- `rbacModuleUsersToSearch`
- `rbacVision`, `rbacSpeech`, `rbacDocs`
- `rbacLakeFirstTime`, `rbacLakeAml`
- `rbacKeyvaultCommon4Users`
- `rbacExternalBastion`
- `cmnRbacACR`

## Implementation Benefits

### 1. **Reduced Complexity**
- Each deployment handles 500-1000 lines vs 3400+
- Clear separation of concerns
- Easier to understand and maintain

### 2. **Faster Deployment Times**
- Parallel deployment capability
- Smaller ARM templates process faster
- Reduced timeout risks

### 3. **Better Error Handling**
- Isolated failure domains
- Easier troubleshooting
- Targeted redeployments

### 4. **Improved Development Workflow**
- Feature-specific development
- Independent testing
- Selective updates

### 5. **Dependency Management**
- Clear dependency chain
- Controlled deployment order
- Better resource orchestration

## Deployment Sequence

```
1. Foundation (Independent)
   ↓
2. Cognitive Services (Depends on Foundation)
   ↓
3. Core Infrastructure (Depends on Foundation)
   ↓
4. Databases (Depends on Core Infrastructure)
   ↓
5. Compute Services (Depends on Core Infrastructure)
   ↓
6. ML Platform (Depends on Cognitive Services + Core Infrastructure)
   ↓
7. RBAC Security (Depends on ALL previous)
```

## Parameter Strategy

### Shared Parameters File
- Common configuration values
- Subscription/tenant information
- Global settings

### Deployment-Specific Parameters
- Service-specific configuration
- Resource sizing
- Feature flags

## Next Steps

1. Create individual Bicep files for each deployment
2. Extract shared parameters
3. Update Azure DevOps pipeline for sequential deployment
4. Test each deployment independently
5. Implement rollback strategies for each layer

This approach will significantly improve maintainability, deployment reliability, and development velocity.
