# Install Azure PowerShell module if not already installed
# Install-Module -Name Az -AllowClobber -Force

# Connect to your Azure account
# Connect-AzAccount

$subscriptionId = 'todo_id'

$context = Get-AzSubscription -SubscriptionId $subscriptionId
Set-AzContext $context

# Variables
$servicePrincipalObjectId = "serivcePrincipalId" # ObjectID
$roleName = "Owner"

$resultBefore = Get-AzRoleAssignment -ObjectId $servicePrincipalObjectId -Scope "/subscriptions/${subscriptionId}"
Write-Host 'Roles before:'
Write-Host $resultBefore

# Get the role definition for Owner
$roleDefinition = Get-AzRoleDefinition -Name $roleName

# Assign the Owner role to the service principal
New-AzRoleAssignment -ObjectId $servicePrincipalObjectId -RoleDefinitionId $roleDefinition.Id -Scope "/subscriptions/$subscriptionId"

Write-Host "Owner role assigned to the service principal successfully. Now pringint the roles for the service principal:"

$result = Get-AzRoleAssignment -ObjectId $servicePrincipalObjectId -Scope "/subscriptions/${subscriptionId}"
Write-Host 'Roles after:'
Write-Host $result
