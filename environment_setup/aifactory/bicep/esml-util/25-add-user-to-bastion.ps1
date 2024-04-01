## EDIT per DSVM you want to deploy
$deplName = '25-add-user-to-bastion'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-001'
$technicalAdminsObjectID = '' # Comma separated ObjectIDs of users

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
$locationSuffix = 'weu'
$projectNumber = '001'
$env = 'dev'
$prjResourceSuffix = '-001'

$rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
Write-Host "RG" $rg
$vnetNameBase = 'vnt-esmlcmn'

####### AKS specic end
Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "aifactory\esml-util\24-add-aks.bicep" `
-Name $deplName `
-ResourceGroupName $rg `
-projectNumber $projectNumber `
-env $env `
-commonRGNamePrefix $commonRGNamePrefix `
-location $location `
-locationSuffix $locationSuffix `
-aifactorySuffixRG $aifactorySuffixRG `
-tags $tags `
-prjResourceSuffix $prjResourceSuffix `
-commonResourceSuffix $commonResourceSuffix `
-vnetNameBase $vnetNameBase `
-technicalAdminsObjectID $technicalAdminsObjectID `
-Verbose

Write-Host "BICEP success!"