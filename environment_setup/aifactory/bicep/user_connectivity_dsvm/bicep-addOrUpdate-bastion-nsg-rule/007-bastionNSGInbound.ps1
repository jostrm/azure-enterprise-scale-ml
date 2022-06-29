#bicep --version
$rg = 'todo-abc-def-esml-common-weu-dev-001' # common RG
# Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "007-main-bastionNsg.bicep" `
-Name "007-Bastion-AddOrUpdateCommonNSG" `
-ResourceGroupName $rg `
-Mode Incremental `
-Verbose