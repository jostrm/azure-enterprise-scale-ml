param (
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the tenant id")][string]$tenantID,
    [Parameter(Mandatory = $true, HelpMessage = "Subscription id")][string]$subscriptionId,
    [Parameter(Mandatory = $true, HelpMessage = "Project resource group")][string]$resourceGroupName,
    [Parameter(Mandatory = $true, HelpMessage = "ObjectID")][string]$userObjectId
)


if (-not [String]::IsNullOrEmpty($spSecret)) {
    Write-Host "The spID parameter is not null or empty. trying to authenticate to Azure with Service principal"   
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
  
    
  }else {
    Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
  }


# One user
az role assignment list --assignee $userObjectId --resource-group $resourceGroupName --output table

# Multiple users
$oids = @(
    "a",
    "b"
)

foreach ($oid in $oids) {
    az role assignment list --assignee $oid --resource-group $resourceGroupName --output table
}