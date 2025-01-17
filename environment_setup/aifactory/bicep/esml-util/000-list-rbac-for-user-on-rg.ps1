# .\aifactory-templates\esml-util\000-list-rbac-for-user-on-rg.ps1 -spID "b7fd945b-4acd-454b-8db4-fa6752ea1c27" -tenantID "720b637a-655a-40cf-816a-f22f40755c2c" -subscriptionId "af154288-535b-47a4-b219-4b4509c4c8d1" -resourceGroupName "ingka-aif-esml-project004-swe-dev-002-rg" -userObjectId "262dfa84-bc95-4191-adcb-cb9398ca1741" -serviceName "aisearchprj003swedevh7amw001"
param (
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the tenant id")][string]$tenantID,
    [Parameter(Mandatory = $true, HelpMessage = "Subscription id")][string]$subscriptionId,
    
    [Parameter(Mandatory = $true, HelpMessage = "Project resource group")][string]$resourceGroupName,
    [Parameter(Mandatory = $true, HelpMessage = "user Object ID")][string]$userObjectId,
    [Parameter(Mandatory = $true, HelpMessage = "Azure Service name")][string]$serviceName
)


if (-not [String]::IsNullOrEmpty($spSecret)) {
    Write-Host "The spID parameter is not null or empty. trying to authenticate to Azure with Service principal"   
    $SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
    $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
    Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID
    $context = Get-AzSubscription -SubscriptionId $subscriptionID
    Set-AzContext $context
    Write-Host "Now connected & logged in with SP successfully!"
  
    if ($(Get-AzContext).Subscription -ne "") {
      write-host "Successfully logged in as $($(Get-AzContext).Account) to $($(Get-AzContext).Subscription)"
    }
    else {
      Write-Host "Failed to login to Azure with Service Principal. Exiting..."
    }
  
    
  }else {
    Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
  }

# One user
az role assignment list --assignee $userObjectId --resource-group $resourceGroupName --output table

# Microsoft.MachineLearningServices
# Microsoft.Storage
# Microsoft.Search
$mlPrefix = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroupName/providers/Microsoft.MachineLearningServices/workspaces/"
$storagePrefix = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroupName/providers/Microsoft.Storage/storageAccounts/"
$searchPrefix = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroupName/providers/Microsoft.Search/searchServices/"

$scopeService = "$searchPrefix$serviceName"

if ($null -ne $scopeService -and $scopeService -ne '') {
  Write-Output "scopeService is not empty or null"
  az role assignment list --assignee $userObjectId --scope $scopeService --output table
} else {
  Write-Output "scopeService is empty or null"
}

# Multiple users
$oids = @(
    
)

#foreach ($oid in $oids) {
#    az role assignment list --assignee $oid --resource-group $resourceGroupName --output table
#}