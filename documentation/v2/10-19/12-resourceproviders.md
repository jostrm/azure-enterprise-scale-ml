# Resource providers - to register, on Azure subscription

If you have a blank Azure subscription, the resource providers for all services needs. 

- ESML AIFactory Automation script: Powershell script to `register mandatory resource provider if not exists` exists here: 
    - [azure-enterprise-scale-ml\environment_setup\aifactory\bicep\esml-util\26-enable-resource-providers.ps1](../../../environment_setup/aifactory/bicep/esml-util/26-enable-resource-providers.ps1)
- [More info - Microsoft docs: resource providers](https://portal.azure.com/#todo/resource/subscriptions/todo-subscription-id/resourceproviders)
- [More info - Microsoft docs: which service needs what provider](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/azure-services-resource-providers)

# INFO - What resource providers are we talking about:
## NEW: AIFactory needs these (AIFactory Common + ESML project)

- Microsoft.Security
- microsoft.insights
- Microsoft.Notebooks
- Microsoft.SqlVirtualMachine
- Microsoft.MachineLearningServices
- Microsoft.DataFactory
- Microsoft.Databricks
- Microsoft.KeyVault
- Microsoft.OperationalInsights
- Microsoft.Kubernetes
- Microsoft.KubernetesConfiguration
- Microsoft.KubernetesRuntime
- Microsoft.ContainerRegistry
- Microsoft.ContainerInstance
- Microsoft.ContainerService
- Microsoft.EventGrid
- Microsoft.EventHub
- Microsoft.VirtualMachineImages
- Microsoft.Storage
- Microsoft.Network
- Microsoft.Compute
- Microsoft.ManagedIdentity
- Microsoft.DataLakeStore
- Microsoft.Batch
- Microsoft.ManagedServices

### ESGenAI project specific: AI Search, Azure OpenAI/Speech, CosmosDB, Azure App Service, Azure API mgmt, Copilot Studio
- Microsoft.Search
- Microsoft.CognitiveServices
- Microsoft.DocumentDB
- Microsoft.AppConfiguration
- Microsoft.DomainRegistration
- Microsoft.CertificateRegistration
- Microsoft.Web
- Microsoft.ApiManagement
- Microsoft.PowerPlatform

### ESSpeech project: Video Indexer, Speech Service
- Microsoft.Media
- Microsoft.CognitiveServices

## To check & verify: These are usually registered, already, but verify:

- Microsoft.OperationsManagement
- Microsoft.Management
- Microsoft.ResourceHealth
- Microsoft.ResourceNotifications
- Microsoft.Resources
- Microsoft.SerialConsole
- microsoft.support
- Microsoft.ResourceGraph
- Microsoft.Portal
- Microsoft.PolicyInsights
- Microsoft.MarketplaceOrdering
- Microsoft.MarketplaceNotifications
- Microsoft.Features
- Microsoft.GuestConfiguration
- Microsoft.DevTestLab
- Microsoft.CostManagement
- Microsoft.Capacity
- Microsoft.ChangeAnalysis
- Microsoft.ClassicSubscription
- Microsoft.CloudShell
- Microsoft.Commerce
- Microsoft.Consumption

## Not included in Powershell script - OPTIONAL & MANUAL: 
For: Purview, BotService, PowerBI, PowerBIEmbedded, Azure ContainerApps, Azure SQL Database/MI/SynapseAnalytics, Azure Arc-enabled Kubernetes, LogicApps

- Microsoft.BotService
- Microsoft.Purview
- Microsoft.PowerBI
- Microsoft.PowerBIDedicated
- Microsoft.App
- Microsoft.Sql
- Microsoft.Kubernetes
- Microsoft.KubernetesConfiguration
- Microsoft.Logic