# Connect to your Azure account
Connect-AzAccount -Tenant 'TODO_tenantID'

$subscriptionId ='todo_subID'
$context = Get-AzSubscription -SubscriptionId $subscriptionId
Set-AzContext $context

# Variables
$servicePrincipalObjectId = 'todo_objectID_of_servicePrincipal' # ObjectID
$vNetResourceGroup = "TODO_RG_where_vNET_and_PrivateDNSZone_is"

$roleName1 = "Private DNS Zone Contributor"
$roleName2 = "Network Contributor"

# Get the role definition for Owner
$roleDefinition1 = Get-AzRoleDefinition -Name $roleName1
$roleDefinition2 = Get-AzRoleDefinition -Name $roleName2

#$rgLevelScope = "/subscriptions/${subscriptionId}/resourceGroups/${vNetResourceGroup}"

# RG LEVEL Assign the Owner role to the service principal
New-AzRoleAssignment -ObjectId $servicePrincipalObjectId -RoleDefinitionId $roleDefinition1.Id -Scope "/subscriptions/$subscriptionId"
New-AzRoleAssignment -ObjectId $servicePrincipalObjectId -RoleDefinitionId $roleDefinition2.Id -Scope "/subscriptions/$subscriptionId"

# SUB LEVEL Assign the roles to the service principal

<# Only if vNet and Private DNS Zones are in different ResourceGroups in the same subscription. Or change subscriptionId
New-AzRoleAssignment -ObjectId $servicePrincipalObjectId -RoleDefinitionId $roleDefinition1.Id -Scope "/subscriptions/$subscriptionId"
New-AzRoleAssignment -ObjectId $servicePrincipalObjectId -RoleDefinitionId $roleDefinition2.Id -Scope "/subscriptions/$subscriptionId"
#>

Write-Output "Private DNS Zone Contributor, Network Contributor roles assigned to the service principal successfully."
