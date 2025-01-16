# USAGE: .\aifactory\esml-util\27-create-private-dns-zones.ps1 -spID TODO -tenantID TODO -subscriptionID TODO8d1 -resourceGroupName TODO -location 'swedencentral' -vnetName 'TODO' -vnetNameResourceGroup 'TODO'
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $true, HelpMessage = "Subscription for Private DNS Zones ")][string]$subscriptionID,
    [Parameter(Mandatory = $true, HelpMessage = "ResourceGroup for Private DNS Zones. rg-esml-common or rg-aifactory-hub ")][string]$resourceGroupName,
    [Parameter(Mandatory = $true, HelpMessage = "vNet name Usually same as Private DNS Zones")][string]$vnetName,
    [Parameter(Mandatory = $true, HelpMessage = "vNet ResourceGroup for vNet.Usually same as Private DNS Zones")][string]$vnetNameResourceGroup,
    [Parameter(Mandatory = $true, HelpMessage = "location")][string]$location
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

  $deplName = '27-create-private-dns-zones'

  Write-Host "Kicking off the BICEP..."
  Set-AzDefault -ResourceGroupName $resourceGroupName
  
  New-AzResourceGroupDeployment -TemplateFile "azure-enterprise-scale-ml\environment_setup\aifactory\bicep\modules\createPrivateDnsZones.bicep" `
  -Name $deplName `
  -ResourceGroupName $resourceGroupName `
  -location $location `
  -privDnsSubscription $subscriptionID `
  -privDnsResourceGroup $resourceGroupName `
  -vNetName $vnetName `
  -vNetResourceGroup $vnetNameResourceGroup `
  -allGlobal $false `
  -Verbose
  
  Write-Host "BICEP success!"