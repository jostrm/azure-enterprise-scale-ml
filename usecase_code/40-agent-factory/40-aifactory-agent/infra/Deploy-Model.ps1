param(
    [Parameter(Mandatory = $true)][string]$Config,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$scope = @($settings.scopes.PSObject.Properties.Value)[0]
$sub = [string]$scope.subscription_id
$rg = [string]$scope.resource_group
$account = [string]$settings.azure.foundry_account
$desired = $settings.azure
$models = az cognitiveservices account list-models --subscription $sub `
    --resource-group $rg --name $account --output json --only-show-errors | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Model catalog discovery failed.' }
$match = @($models | Where-Object {
    $_.name -eq $desired.model_name -and $_.version -eq $desired.model_version
})
if ($match.Count -ne 1 -or $match[0].capabilities.agentsV2 -ne 'true' -or
    $match[0].capabilities.responses -ne 'true') {
    throw 'Requested model/version is not advertised for Foundry Agents/Responses. Do not substitute.'
}
if ($desired.model_sku -notin @($match[0].skus.name)) {
    throw 'Requested deployment tier is not advertised for the selected account/model.'
}
$deployments = az cognitiveservices account deployment list --subscription $sub `
    --resource-group $rg --name $account --output json --only-show-errors | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Deployment inventory failed.' }
$existing = @($deployments | Where-Object { $_.name -eq $desired.model_deployment })
if ($existing.Count -gt 0) {
    if ($existing[0].properties.model.name -ne $desired.model_name -or
        $existing[0].properties.model.version -ne $desired.model_version -or
        $existing[0].sku.name -ne $desired.model_sku -or
        $existing[0].sku.capacity -ne $desired.model_capacity) {
        throw 'Existing deployment differs from the approved configuration; review drift before changing it.'
    }
    $existing[0] | Select-Object name, sku, properties | ConvertTo-Json -Depth 10
    return
}
$plan = @{
    subscription = $sub; resource_group = $rg; account = $account
    deployment = $desired.model_deployment; model = $desired.model_name
    version = $desired.model_version; sku = $desired.model_sku
    capacity = $desired.model_capacity; operation = 'create-model-deployment'
    cost = 'Use verified model rates; inference charges are additional.'
}
$plan | ConvertTo-Json
if (-not $Apply) { return }
az cognitiveservices account deployment create --subscription $sub --resource-group $rg `
    --name $account --deployment-name $desired.model_deployment `
    --model-name $desired.model_name --model-version $desired.model_version `
    --model-format OpenAI --sku-name $desired.model_sku --sku-capacity $desired.model_capacity `
    --query '{name:name,state:properties.provisioningState,model:properties.model,sku:sku}' `
    --output json --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Model deployment failed; inspect the target before any retry.' }
