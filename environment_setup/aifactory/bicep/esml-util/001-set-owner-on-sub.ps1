# Install Azure PowerShell module if not already installed
# Install-Module -Name Az -AllowClobber -Force

# Connect to your Azure account
# Connect-AzAccount

$subscriptionId = 'todo_id'

$context = Get-AzSubscription -SubscriptionId $subscriptionId
Set-AzContext $context

# Variables
$servicePrincipalId = "serivcePrincipalId" # AppID or ObjectID?
$roleName = "Owner"

# Get the role definition for Owner
$roleDefinition = Get-AzRoleDefinition -Name $roleName

# Assign the Owner role to the service principal
New-AzRoleAssignment -ObjectId $servicePrincipalId -RoleDefinitionId $roleDefinition.Id -Scope "/subscriptions/$subscriptionId"

Write-Output "Owner role assigned to the service principal successfully."
