## EDIT per DSVM you want to deploy
$deplName = '24-add-aks'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-001'

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

$location = 'westeurope'
$projectNumber = '001'
$env = 'dev'
$locationSuffix = 'weu'
$prjResourceSuffix = '-001'

$rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
Write-Host "RG" $rg

$vnetNameBase = 'vnt-esmlcmn'

####### AKS Specific
$aksSuffix = '' # 1 char only

$ownSSL = 'disabled'
$aksCert = ''
$aksCname = ''
$aksCertKey = ''
$aksSSLstatus = ''

####### AKS specic end
Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "aifactory\esml-util\24-add-aks.bicep" `
-Name $deplName `
-ResourceGroupName $rg `
-projectNumber $projectNumber `
-env $env `
-commonRGNamePrefix $commonRGNamePrefix `
-locationSuffix $locationSuffix `
-aifactorySuffixRG $aifactorySuffixRG `
-tags $tags `
-location $location `
-prjResourceSuffix $prjResourceSuffix `
-commonResourceSuffix $commonResourceSuffix `
-vnetNameBase $vnetNameBase `
-ownSSL $ownSSL `
-aksCert $aksCert `
-aksCname $aksCname `
-aksCertKey $aksCertKey `
-aksSSLstatus $aksSSLstatus `
-aksSuffix $aksSuffix `
-Verbose

Write-Host "BICEP success!"