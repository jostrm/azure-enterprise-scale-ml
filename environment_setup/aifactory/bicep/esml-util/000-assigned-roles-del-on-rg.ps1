az login --tenant ""
#$context = Get-AzSubscription -SubscriptionId ""
#Set-AzContext $context

####### EDIT VARIABLES ####
$subscriptionId = ""
$resourceGroupName = ""
$resourceGroupNameCommon = ""

# Define the list of OIDs of users
$oids = @(
    ""
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
    "b24988ac-6180-42a0-ab88-20f7382dd24c" # "Contributor"
    "8311e382-0749-4cb8-b61a-304f252e45ec" # "AcrPush"
    "3afb7f49-54cb-416e-8c09-6dc049efa503" # "Azure AI Inference Deployment Operator"
    "ea01e6af-a1c1-4350-9563-ad00f8c72ec5" # "Azure Machine Learning Workspace Connection Secrets Reader"
    "f6c7c914-8db3-469d-8ca1-694a8f32e121" #"AzureML Data Scientist"
    "f58310d9-a9f6-439a-9e8d-f62e7b41a168" #"Role Based Access Control Administrator"
    "1c0163c0-47e6-4577-8991-ea5c82e286e4" #"Virtual Machine Administrator Login"
)

# COMMON - USERS
foreach ($oid in $oids) {
    foreach ($role in $rolesCommmonRG) {
        az role assignment delete --assignee-object-id $oid --assignee-principal-type User --role $role --scope $scopeCommon
   }
} 
# PROJECT RG - USERS
foreach ($oid in $oids) {
    foreach ($role in $rolesProjectRG) {
        az role assignment delete --assignee-object-id $oid --assignee-principal-type User --role $role --scope $scopeProjectResourceGroup
    }
}