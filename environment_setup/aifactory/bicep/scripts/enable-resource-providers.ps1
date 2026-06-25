param (
    [Parameter(Mandatory=$true)]
    [string]$SubscriptionName,
    [Parameter(Mandatory=$false)]
    [bool]$Readonly = $false
)

[string]$ScriptPath = $(if ([string]::IsNullOrEmpty($PSScriptRoot)) { $PSScriptRoot } else { split-path -parent $MyInvocation.MyCommand.Path })
[string]$ScriptNameSimple = $(if ([string]::IsNullOrEmpty($PSCommandPath)) { (split-path -leaf $PSCommandPath).Split('.')[0] } else { $MyInvocation.MyCommand.Name.Split('.')[0] })
function GetDateTime () {
    return $(Get-Date -Format yyyyMMdd-hhmmss)
}
function Logging ([string]$_LogText) {
    Write-Host $_LogText
    $_LogText | Out-File -FilePath $logPath -Append
}

$logPath = Join-Path $ScriptPath $('{0}_{1}_{2}.log' -f $ScriptNameSimple, $SubscriptionName, $(GetDateTime))

$ResourceProviders = @(
'Microsoft.Batch'
'Microsoft.Capacity'
'Microsoft.ChangeAnalysis'
'Microsoft.ClassicSubscription'
'Microsoft.CloudShell'
'Microsoft.Commerce'
'Microsoft.Compute'
'Microsoft.Consumption'
'Microsoft.ContainerInstance'
'Microsoft.ContainerRegistry'
'Microsoft.ContainerService'
'Microsoft.CostManagement'
'Microsoft.Databricks'
'Microsoft.DataFactory'
'Microsoft.DataLakeStore'
'Microsoft.DevTestLab'
'Microsoft.EventGrid'
'Microsoft.EventHub'
'Microsoft.Features'
'Microsoft.GuestConfiguration'
'microsoft.insights'
'Microsoft.KeyVault'
'Microsoft.Kubernetes'
'Microsoft.KubernetesConfiguration'
'Microsoft.KubernetesRuntime'
'Microsoft.MachineLearningServices'
'Microsoft.ManagedIdentity'
'Microsoft.ManagedServices'
'Microsoft.Management'
'Microsoft.MarketplaceNotifications'
'Microsoft.MarketplaceOrdering'
'Microsoft.Network'
'Microsoft.Notebooks'
'Microsoft.OperationalInsights'
'Microsoft.OperationsManagement'
'Microsoft.PolicyInsights'
'Microsoft.Portal'
'Microsoft.ResourceGraph'
'Microsoft.ResourceHealth'
'Microsoft.ResourceNotifications'
'Microsoft.Resources'
'Microsoft.Security'
'Microsoft.SerialConsole'
'Microsoft.SqlVirtualMachine'
'Microsoft.Storage'
'microsoft.support'
'Microsoft.VirtualMachineImages'
'Microsoft.Search'
'Microsoft.CognitiveServices'
'Microsoft.DocumentDB'
'Microsoft.AppConfiguration'
'Microsoft.DomainRegistration'
'Microsoft.CertificateRegistration'
'Microsoft.Web'
'Microsoft.ApiManagement'
'Microsoft.PowerPlatform'
'Microsoft.Media'
'Microsoft.AlertsManagement'
)

$sub = Select-AzSubscription $SubscriptionName -ErrorAction SilentlyContinue -WarningAction SilentlyContinue
if ($null -ne $sub -and $SubscriptionName -eq $sub.Subscription.Name)
{
    Logging $('Subscription {0} [{1}]' -f $sub.Subscription.Name, $sub.Subscription.Id)
    
    foreach ($resourceProvider in $ResourceProviders)
    {
        $NotRegistered = $null -ne $(Get-AzresourceProvider -ProviderNamespace $ResourceProvider | Where-Object { $_.RegistrationState -eq 'NotRegistered' -and $_.RegistrationState -ne 'Registered' })

        if ($NotRegistered -eq $true)
        {
            Logging $('  Registering Resource Provider [{0}]...' -f $resourceProvider)
            if ($readOnly -ne $true)
            {
                try
                {
                    $regProvider = Register-AzResourceProvider -ProviderNamespace $resourceProvider
                }
                catch
                {
                    Logging $error[0]
                }
            }
        }
        else
        {
            Logging $('  Resource Provider [{0}] already registered!' -f $resourceProvider)
        }
    }
}
else
{
    Logging $('Error: Subscription {0} [{1}] not found!' -f $sub.Name, $sub.Id)
}
Logging "Done!"