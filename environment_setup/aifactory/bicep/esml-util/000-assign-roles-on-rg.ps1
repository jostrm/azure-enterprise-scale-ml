az login --tenant ""
#$context = Get-AzSubscription -SubscriptionId ""
#Set-AzContext $context

####### EDIT VARIABLES ####
$subscriptionId = ""
$resourceGroupName = ""
$resourceGroupNameCommon = ""
$storageAccountName = ""
$storageAccountName2 = ""
$amlWorkspace1 = ""
$amlWorkspace2 = ""
$azureMLObjectID = ""

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

#### INFO ####
# Below roles are distributed on various AI services 
<#  "Azure AI Inference Deployment Operator",
    "Cognitive services Custom Vision Contributor",
    "Search Index Data Contributor", #App service or Function app -> RG
    "Contributor",
    "AcrPush",# SP, user -> RG
    "AcrPull", #App service or Function app -> RG
    "AzureML Data Scientist", # SP, user -> RG
    "Cognitive Services OpenAI User", #SP, User, App service or Function app -> RG
    "Azure Machine Learning Workspace Connection Secrets Reader", # ai-project, SP, User -> RG
    "Search Service Contributor",
    "Azure AI Developer", #SP and user -> AI hub
    "Azure AI Inference Deployment Operator", # user -> AI project
    "User Access Administrator" # -> (optional) jostrm
    "Storage File Data Privileged Contributor",
    "Storage Blob Data Contributor" 
#>
#### END INFO ####

# Scopes
$scopeCommon = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupNameCommon"
$saScope = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.Storage/storageAccounts/$storageAccountName"
$saScope2 = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.Storage/storageAccounts/$storageAccountName2"
$amlScope = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.MachineLearningServices/workspaces/$amlWorkspace1"
$amlScope2 = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.MachineLearningServices/workspaces/$amlWorkspace2"
$scopeResourceGroup = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName"
#$scopeSubscription = "/subscriptions/$subscriptionId"

$rolesSa = @(
    "Storage File Data Privileged Contributor",
    "Storage Blob Data Contributor"
)
$rolesRGAml = @(
    "AzureML Data Scientist", # SP, user -> RG
    "Azure Machine Learning Workspace Connection Secrets Reader", # ai-project, SP, User -> RG
    "Azure AI Developer" #SP and user -> AI hub
)

$rolesRGCommonACR = @(
    "AcrPush",# SP, user -> RG
    "AcrPull" #App service or Function app -> RG
)

## SA 1
foreach ($oid in $oids) {
    foreach ($role in $rolesSa) {
        az role assignment create --assignee-object-id $oid --assignee-principal-type User --role $role --scope $saScope
    }
}
## SA 2
foreach ($oid in $oids) {
    foreach ($role in $rolesSa) {
        az role assignment create --assignee-object-id $oid --assignee-principal-type User --role $role --scope $saScope2
    }
}
## aml 1
foreach ($oid in $oids) {
    foreach ($role in $rolesRGAml) {
        az role assignment create --assignee-object-id $oid --assignee-principal-type User --role $role --scope $amlScope
    }
}
## aml 2
foreach ($oid in $oids) {
    foreach ($role in $rolesRGAml) {
        az role assignment create --assignee-object-id $oid --assignee-principal-type User --role $role --scope $amlScope2
    }
}

# COMMON - Shared ACR - Roles: AcrPush, AcrPull
foreach ($oid in $oids) {
    foreach ($role in $rolesRGCommonACR) {
        az role assignment create --assignee-object-id $oid --assignee-principal-type User --role $role --scope $scopeCommon
    }
}

# Loop through each email address and assign the role
foreach ($oid in $managedIdentities) {
    foreach ($role in $rolesRGCommonACR) {
        az role assignment create --assignee-object-id $oid --assignee-principal-type ServicePrincipal --role $role --scope $scopeCommon
    }
}

# Azure ML
az role assignment create --assignee-object-id $azureMLObjectID --assignee-principal-type ServicePrincipal --role "Reader" --scope $scopeResourceGroup


