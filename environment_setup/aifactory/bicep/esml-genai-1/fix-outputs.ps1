# PowerShell script to replace all direct output references with variables

$filePath = "32-main.bicep"
$backupPath = "32-main.bicep.backup-outputs"

# Create backup
Copy-Item $filePath $backupPath -Force
Write-Host "Created backup: $backupPath"

# Read the file content
$content = Get-Content $filePath -Raw

# Define replacement mappings
$replacements = @{
    "dnsConfig: csSpeech.outputs.dnsConfig" = "dnsConfig: var_csSpeech_dnsConfig"
    "dnsConfig: csDocIntelligence.outputs.dnsConfig" = "dnsConfig: var_csDocIntelligence_dnsConfig"
    "dnsConfig: csAzureOpenAI.outputs.dnsConfig" = "dnsConfig: var_csAzureOpenAI_dnsConfig"
    "dnsConfig: enableAISearch\? aiSearchService.outputs.dnsConfig:\[\]" = "dnsConfig: var_aiSearchService_dnsConfig"
    "dnsConfig: sa4AIsearch.outputs.dnsConfig" = "dnsConfig: var_sa4AIsearch_dnsConfig"
    "dnsConfig: sacc.outputs.dnsConfig" = "dnsConfig: var_sacc_dnsConfig"
    "dnsConfig: kv1.outputs.dnsConfig" = "dnsConfig: var_kv1_dnsConfig"
    "dnsConfig: acr.outputs.dnsConfig" = "dnsConfig: var_acr_dnsConfig"
    "dnsConfig: cosmosdb.outputs.dnsConfig" = "dnsConfig: var_cosmosdb_dnsConfig"
    "dnsConfig: postgreSQL.outputs.dnsConfig" = "dnsConfig: var_postgreSQL_dnsConfig"
    "dnsConfig: redisCache.outputs.dnsConfig" = "dnsConfig: var_redisCache_dnsConfig"
    "dnsConfig: sqlServer.outputs.dnsConfig" = "dnsConfig: var_sqlServer_dnsConfig"
    "dnsConfig: containerAppsEnv.outputs.dnsConfig" = "dnsConfig: var_containerAppsEnv_dnsConfig"
    "dnsConfig: webapp.outputs.dnsConfig" = "dnsConfig: var_webapp_dnsConfig"
    "dnsConfig: function.outputs.dnsConfig" = "dnsConfig: var_function_dnsConfig"
    "cosmosName: cosmosdb.outputs.name" = "cosmosName: var_cosmosdb_name"
    "postgreSqlServerName: postgreSQL.outputs.name" = "postgreSqlServerName: var_postgreSQL_name"
    "redisName: redisCache.outputs.name" = "redisName: var_redisCache_name"
    "sqlServerName: sqlServer.outputs.serverName" = "sqlServerName: var_sqlServer_serverName"
    "containerRegistryName: acrCommon2.outputs.containerRegistryName" = "containerRegistryName: var_acrCommon2_containerRegistryName"
    "containerRegistryName: acr.outputs.containerRegistryName" = "containerRegistryName: var_acr_containerRegistryName"
    "appInsightsName:applicationInsightSWC.outputs.name" = "appInsightsName: var_applicationInsightSWC_name"
    "applicationInsightsName: resourceExists.applicationInsight\? applicationInsightName: applicationInsightSWC.outputs.name" = "applicationInsightsName: resourceExists.applicationInsight? applicationInsightName: var_applicationInsightSWC_name"
    "acrName: resourceExists.acrProject\? acrProjectName:acr.outputs.containerRegistryName" = "acrName: resourceExists.acrProject? acrProjectName: var_acr_containerRegistryName"
    "aiHubName: enableAIFoundryHub\? \(resourceExists.aiHub\? aiHubName:aiHub.outputs.name\): ''" = "aiHubName: var_aiHub_name"
    "visonServiceName: csVision.outputs.name" = "visonServiceName: var_csVision_name"
    "speechServiceName: csSpeech.outputs.name" = "speechServiceName: var_csSpeech_name"
    "docsServiceName: csDocIntelligence.outputs.name" = "docsServiceName: var_csDocIntelligence_name"
}

# Apply replacements
$modifiedCount = 0
foreach ($search in $replacements.Keys) {
    $replace = $replacements[$search]
    $originalContent = $content
    $content = $content -replace $search, $replace
    if ($content -ne $originalContent) {
        $modifiedCount++
        Write-Host "Replaced: $search -> $replace"
    }
}

# Write the modified content back to the file
Set-Content $filePath $content -NoNewline

Write-Host "Modification complete! Made $modifiedCount replacements."
Write-Host "Original file backed up as: $backupPath"
Write-Host ""
Write-Host "You can now test with: az bicep build --file 32-main.bicep"
