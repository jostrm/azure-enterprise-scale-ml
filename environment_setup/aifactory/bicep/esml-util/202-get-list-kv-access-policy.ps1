param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal, to login with")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the app id for service principal, to login with")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the object id for service principal, to assign GET, LIST Access policy")][string]$target_spOID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory keyvault name")][string]$keyvaultName,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory subscription id")][string]$subscription_id
)

# Login with the service principal
$SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
$credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID

$context = Get-AzSubscription -SubscriptionId $subscriptionID
Set-AzContext $context

# Set the Key Vault access policy
Set-AzKeyVaultAccessPolicy -VaultName $keyVaultName -ObjectId $target_spOID -PermissionsToSecrets get,list -BypassObjectIdValidation