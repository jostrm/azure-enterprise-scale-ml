# bicep --version

#esml-project: rbacDBX2AazureMLwithProjectSP{001}{weu}{dev}
## 33 deployments (+failureAnomaly)
## This executes the last 3 deployments of 33 (29-33), in main.bicep

#1)## rbacDBX2AMLProjectSPSWC001weudev
#2)## rbacADFFromAMLorProjSP001weudev
#3)## rbacDatabricks2AazureMLwithProjectSP002weudev 

$rg = 'todo-esml-project002-weu-dev-001-rg'
$env = 'dev'
$locationSuffix = 'weu'
$projectNumber = '002'
$amlName = 'aml-prj002-weu-dev-001'
$adfName = 'adf-prj002-weu-dev-fn2ym-001'

$projectServicePrincipleOID = 'todo_esml-project001-sp-oid' # project specific
$adfPrincipalId = 'todo_adf-managedIdentity-oid' # Managed Identity/Object ID
$technicalContactId = 'todo-batman-aduser-oid'
$technicalAdminsObjectID = 'todo-batman-aduser-oid, todo-robin-aduser-oid,todo-riddler-aduser-oid' # Comma separated

$deplName = '100-aml-rbac-bicep'

Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "aifactory\esml-util\100-aml-rbac.bicep" `
-Name $deplName `
-ResourceGroupName $rg `
-env $env `
-locationSuffix $locationSuffix `
-projectNumber $projectNumber `
-amlName $amlName `
-adfName $adfName `
-projectServicePrincipleOID $projectServicePrincipleOID `
-adfPrincipalId $adfPrincipalId `
-technicalContactId $technicalContactId `
-technicalAdminsObjectID $technicalAdminsObjectID `
-Verbose

Write-Host "BICEP success!"