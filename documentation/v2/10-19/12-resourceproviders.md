# Resource providers - to register, on Azure subscription

If you have a blank Azure subscription, the resource providers for all services needs. 

- ESML AIFactory Automation script: Powershell script to `register mandatory resource provider if not exists` exists here: 
    - [azure-enterprise-scale-ml\environment_setup\aifactory\bicep\esml-util\26-enable-resource-providers.ps1](../../../environment_setup/aifactory/bicep/esml-util/26-enable-resource-providers.ps1)
- [More info - Microsoft docs: resource providers](https://portal.azure.com/#todo/resource/subscriptions/todo-subscription-id/resourceproviders)
- [More info - Microsoft docs: which service needs what provider](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/azure-services-resource-providers)

# Prerequisites
Prerequisites: You need to [install Azure Powershell](https://learn.microsoft.com/en-us/powershell/azure/install-azps-windows?view=azps-12.2.0&tabs=powershell&pivots=windows-psgallery) to run this script, [or you can run this in Azure Cloud Shell (Powershell)](https://learn.microsoft.com/en-us/azure/cloud-shell/get-started/classic?tabs=azurecli)

# HowTo: login & Run

Foreach subscription: 
- Login, as in [this script](../../../../aifactory/esml-util/000-switch-sub2_dev.ps1)
- Run this [this script](../../../../aifactory/esml-util/26-enable-resource-providers.ps1)

# INFO - What resource providers are we talking about:
# IMPORTANT - AKS, Kubernetes and Private DNS Zones

If not running the AIFactory standalone. E.g. if use have centrlazied private DNS Zones - **the private DNS zone is in a different subscription than the AKS cluster, you need to register the Azure provider `Microsoft.ContainerService` in both subscriptions**

[Read more - AKS private clusters with Custom Private DNS zone](https://learn.microsoft.com/en-us/azure/aks/private-clusters?tabs=azure-portal)


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
- Microsoft.AlertsManagement

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
- Microsoft.CognitiveServices (also in ESGenAI)

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