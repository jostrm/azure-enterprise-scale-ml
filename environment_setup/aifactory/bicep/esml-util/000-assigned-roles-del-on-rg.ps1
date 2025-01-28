param (
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the tenant id")][string]$tenantID,
    [Parameter(Mandatory = $true, HelpMessage = "Subscription id")][string]$subscriptionId,
    
    [Parameter(Mandatory = $false, HelpMessage = "Project resource group")][string]$resourceGroupName,
    [Parameter(Mandatory = $false, HelpMessage = "COmmon ResourceGroup")][string]$resourceGroupNameCommon
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

# EDIT Variables
$oids = @(

)
# Define the list of MI IDs
$managedIdentities = @(
    "", # AML 1 OID MI
    "" # AML 2 OID MI
)

####### END - EDIT VARIABLES####

# Scopes
$scopeCommon = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupNameCommon"
$rolesCommmonRG = @(
    "8311e382-0749-4cb8-b61a-304f252e45ec" # "AcrPush"
)

$scopeProjectResourceGroup = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName"
$rolesProjectRG = @(
    "b24988ac-6180-42a0-ab88-20f7382dd24c", # "Contributor"
    "8311e382-0749-4cb8-b61a-304f252e45ec", # "AcrPush"
    "3afb7f49-54cb-416e-8c09-6dc049efa503", # "Azure AI Inference Deployment Operator"
    "ea01e6af-a1c1-4350-9563-ad00f8c72ec5",# "Azure Machine Learning Workspace Connection Secrets Reader"
    "f6c7c914-8db3-469d-8ca1-694a8f32e121", #"AzureML Data Scientist"
    "f58310d9-a9f6-439a-9e8d-f62e7b41a168", #"Role Based Access Control Administrator"
    "1c0163c0-47e6-4577-8991-ea5c82e286e4" #"Virtual Machine Administrator Login"
)

Write-Host "Deleting roles on resource group $scopeProjectResourceGroup"
Write-Host ""

# PROJECT RG - USERS
foreach ($oid in $oids) {
    foreach ($role in $rolesProjectRG) {
        az role assignment delete --assignee $oid --role $role --scope $scopeProjectResourceGroup
    }
}

Write-Host "Deleting roles on resource group $resourceGroupNameCommon"
Write-Host ""
# COMMON - USERS
foreach ($oid in $oids) {
    foreach ($role in $rolesCommmonRG) {
        az role assignment delete --assignee $oid --role $role --scope $scopeCommon
   }
} 

