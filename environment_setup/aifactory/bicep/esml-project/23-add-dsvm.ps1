$Password = New-Object -TypeName PSObject
$Password | Add-Member -MemberType ScriptProperty -Name "Password" -Value { ("!@#$%^&*0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz".tochararray() | sort {Get-Random})[0..8] -join '' }

## EDIT per DSVM you want to deploy
$dsvmNumber = '-004' # update this to an available suffix
$dsvm_pass_4= $Password.Password # 'uT$ENaWvLNSa' # your PWD
$adminPassword = $dsvm_pass_4 | ConvertTo-SecureString -AsPlainText -Force

$deplName = '23-add-dsvm'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-004'

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

$rg = 'abc-def-esml-project002-weu-dev-004-rg'
$env = 'dev'
$locationSuffix = 'weu'
$projectNumber = '002'
$prjResourceSuffix = '-003'
$vnetNameBase = 'vnt-esmlcmn'

Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "./esml-project/23-add-dsvm.bicep" `
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
-Verbose

Write-Host "BICEP success!"