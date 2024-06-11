param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal, to login with")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the app id for service principal, to login with")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory=$true, HelpMessage="An array / list of object id's for users and service principals, to assign GET, LIST Access policy")][string[]]$userObjectIds,
    [Parameter(Mandatory = $true, HelpMessage = "project = GET,LIST , coreteam = GET,LIST,SET")][string]$projectOrCoreteam = 'project',
    [Parameter(Mandatory = $true, HelpMessage = "ESML AIFactory keyvault name")][string]$keyvaultName,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AIFactory subscription id")][string]$subscriptionID

)

if (-not [String]::IsNullOrEmpty($spSecret)) {
    Write-Host "The spID parameter is not null or empty. trying to authenticate to Azure with Service principal"
    #Write-Host "The spID: ${spID}"
    #Write-Host "The tenantID: ${tenantID}"
  
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
} else {
    # The $spID parameter is null or empty
    Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
}

# All users in project
for ($i=0; $i -lt $userObjectIds.Length; $i++) {
    $targetObjectID = $userObjectIds[$i]
    if ($projectOrCoreteam -eq "project") {
        Set-AzKeyVaultAccessPolicy -VaultName $keyVaultName -ObjectId $targetObjectID -PermissionsToSecrets get,list -BypassObjectIdValidation
    } elseif ($projectOrCoreteam -eq "coreteam") {
        Set-AzKeyVaultAccessPolicy -VaultName $keyVaultName -ObjectId $targetObjectID -PermissionsToSecrets get,list,set -BypassObjectIdValidation
    }
    
}