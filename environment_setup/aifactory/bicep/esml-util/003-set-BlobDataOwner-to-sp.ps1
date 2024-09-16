# USAGE: 
.\201-az-cli-give-role.ps1 -spID '4885c3c2-702b-4b30-8cc3-dafc6acf3a4c' -target_spOID '00e70fc7-8f6d-46bc-a051-d6e004558d3b' -tenantID 'b7872ef0-9a00-4c18-8a4a-c7d25c778a9e' -subscription_id '451967ad-7751-478e-8c64-cd0e7afa64ed' -resource_group 'sweco-1-esml-common-sdc-dev-001' -storageAccountName 'sweco1mt4t7esml001dev'

# DESCRIPTION:# ow to give azure role Storage Blob Data Owner on a storage account with powershell (and/or Owner on Keyvault), logging in with a service principal, giving another service principal that role.
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

# AZ EXAMPLE - does not work (may require AD graph access)
#az login --service-principal --tenant <tenant-id> -u <service-principal-id> -p <service-principal-secret>
#az extension add -n storage-preview
#az role assignment create --assignee <service-principal-id> --role "Storage Blob Data Owner" --scope "/subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.Storage/storageAccounts/<storage-account-name>"