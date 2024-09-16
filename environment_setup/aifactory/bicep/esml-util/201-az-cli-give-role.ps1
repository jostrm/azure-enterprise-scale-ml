param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal, to login with")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the app id for service principal, to login with")][string]$spID,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the object id for service principal, to assign Storage Blob Data Owner role")][string]$target_spOID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccountName,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory keyvault name")][string]$keyvaultName,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory subscription id")][string]$subscription_id,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory resource_group name")][string]$resource_group
)
#How to give azure role Storage Blob Data Owner on a storage account with powershell, logging in with a service principal, giving another service principal that role.

$SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
$credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID

Get-AzRoleAssignment -ObjectId $target_spOID -Scope "/subscriptions/${subscription_id}/resourceGroups/${resource_group}"

if (-not [String]::IsNullOrEmpty($storageAccountName)) {
    Write-Host "The parameter storageAccountName is set."
    New-AzRoleAssignment -ObjectId $target_spOID -RoleDefinitionName "Storage Blob Data Owner" -Scope "/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.Storage/storageAccounts/${storageAccountName}"
}
if (-not [String]::IsNullOrEmpty($keyvaultName)) {
    Write-Host "The parameter keyvaultName is set."
    New-AzRoleAssignment -ObjectId $target_spOID -RoleDefinitionName "Owner" -Scope "/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.KeyVault/vaults/${keyvaultName}"
} 

# AZ EXAMPLE - requires AD graph access
#az login --service-principal --tenant <tenant-id> -u <service-principal-id> -p <service-principal-secret>
#az extension add -n storage-preview
#az role assignment create --assignee <service-principal-id> --role "Storage Blob Data Owner" --scope "/subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.Storage/storageAccounts/<storage-account-name>"
