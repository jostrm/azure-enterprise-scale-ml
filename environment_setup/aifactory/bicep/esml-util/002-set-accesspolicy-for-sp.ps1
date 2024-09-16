Connect-AzAccount -Tenant 'TODO_tenantID'

$context = Get-AzSubscription -SubscriptionId 'TODO_subscriptionID'
Set-AzContext $context

$targetObjectID = "TODO-esml-common-bicep-sp-oid value" # Service principal ObjectID for esml-common-bicep-sp
$keyVaultName = "kv-esml-seeding-TODO" 

Set-AzKeyVaultAccessPolicy -VaultName $keyVaultName -ObjectId $targetObjectID -PermissionsToSecrets get,list,set -BypassObjectIdValidation