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

  # Az login
  az login --service-principal -u $spID -p $spSecret --tenant $tenantID
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Logged in with service principal successfully!"
  } else {
      Write-Host "Failed to login with service principal."
      exit 1
  }
  az account set --subscription $subscriptionID

  Write-Host "Now connected & logged in with SP successfully!"
  $context = az account show --query "{Account: name, Subscription: id}" -o json | ConvertFrom-Json
  if ($context.Subscription -ne "") {
      Write-Host "Successfully logged in as $($context.Account) to $($context.Subscription)"
  } else {
      Write-Host "Failed to login to Azure with Service Principal. Exiting..."
      exit 1
  }

  # Powershell login
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

# clear cache
#az config set core.encrypt_token_cache=false
#az account clear
#az config set core.encrypt_token_cache=true

# One user
az role assignment list --assignee $userObjectId --resource-group $resourceGroupName

# Microsoft.MachineLearningServices
# Microsoft.Storage
# Microsoft.Search
$mlPrefix = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroupName/providers/Microsoft.MachineLearningServices/workspaces/"
$storagePrefix = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroupName/providers/Microsoft.Storage/storageAccounts/"
$searchPrefix = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroupName/providers/Microsoft.Search/searchServices/"

$scopeService = "$searchPrefix$serviceName"

if ($null -ne $scopeService -and $scopeService -ne '') {
  Write-Output "scopeService is not empty or null"
  #az role assignment list --assignee $userObjectId --scope $scopeService --output table
  #az role assignment list --assignee $userObjectId --scope $scopeService --output --query '[].{Role:roleDefinitionName,Principal:principalName,Scope:scope}' --output table
} else {
  Write-Output "scopeService is empty or null"
}

# Multiple users
$oids = @(
    
)

#foreach ($oid in $oids) {
#    az role assignment list --assignee $oid --resource-group $resourceGroupName --output table
#}