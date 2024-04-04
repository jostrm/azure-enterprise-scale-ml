# Resource providers - to register, on Azure subscription

If you have a blank Azure subscription, the resrouce providers for all services needs. 

- Powershell script to `register if not exists` exists here: azure-enterprise-scale-ml\environment_setup\aifactory\bicep\esml-util\26-enable-resource-providers.ps1
    - 
- About resource providers: https://portal.azure.com/#todo/resource/subscriptions/todo-subscription-id/resourceproviders

# INFO - What resource providers are we talking about:
## NEW: AIFactory needs these:

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

## To check: Are usually registered, already:

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