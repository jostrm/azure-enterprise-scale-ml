# USAGE: .\aifactory\esml-util\23-add-dsvm.ps1 -spSecret -spID xyz -tenantID abc -subscriptionID xyz
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$subscriptionID
)

if (-not [String]::IsNullOrEmpty($spSecret)) {

  $SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
  $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
  Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID

  $context = Get-AzSubscription -SubscriptionId $subscriptionID
  Set-AzContext $context
} else {
  # The $spID parameter is null or empty
  Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
}

$Password = New-Object -TypeName PSObject
$Password | Add-Member -MemberType ScriptProperty -Name "Password" -Value { ("!@#$%^&*0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz".tochararray() | sort {Get-Random})[0..8] -join '' }

## EDIT per DSVM you want to deploy
$dsvmNumber = '-002' # update this to an available suffix
$dsvm_pass_4= $Password.Password # 'uT$ENaWvLNSa' # your PWD
$adminPassword = $dsvm_pass_4 | ConvertTo-SecureString -AsPlainText -Force

$deplName = '23-add-dsvm'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-001'
$common_subnet_name = 'snet-esml-cmn-001'

$tags = @{
    "Application Name" = "Enterprise Scale ML (ESML)"
    "BA ID" = "NA"
    "BCIO"= "Robin"
    "Business Area"= "NA"
    "Cost Center"="123456"
    "Resource Managed By"="The Riddler"
    "TechnicalContact"="batman@gothamcity.dc"
    "Project"="Batcave upgrade"
    "Description"="ESML AI Factory"
   }

$location = 'uksouth'
$projectNumber = '002'
$env = 'dev'
$locationSuffix = 'uks'
$prjResourceSuffix = '-001'

$rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${prjResourceSuffix}-rg"
$vnetNameBase = 'vnt-esmlcmn'

Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "aifactory\esml-util\23-add-dsvm.bicep" `
-Name $deplName `
-ResourceGroupName $rg `
-projectNumber $projectNumber `
-env $env `
-adminPassword $adminPassword `
-commonRGNamePrefix $commonRGNamePrefix `
-locationSuffix $locationSuffix `
-aifactorySuffixRG $aifactorySuffixRG `
-tags $tags `
-location $location `
-prjResourceSuffix $prjResourceSuffix `
-dsvmSuffix $dsvmNumber `
-commonResourceSuffix $commonResourceSuffix `
-vnetNameBase $vnetNameBase `
-common_subnet_name $common_subnet_name `
-Verbose

Write-Host "BICEP success!"