param(
    [Parameter(Mandatory)][string]$subscriptionId,
    [Parameter(Mandatory)][string]$vnetResourceGroup,
    [Parameter(Mandatory)][string]$vnetName,
    [Parameter(Mandatory)][ValidatePattern('^\d{1,3}$')][string]$projectNumber,
    [string]$enableLogicApps = 'false',
    [string]$logicAppType = 'Standard',
    [string]$byoASEv3 = 'false',
    [string]$enablePublicAccessWithPerimeter = 'false'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'modules\logicAppSubnet.ps1')
$expectedId = "/subscriptions/$subscriptionId/resourceGroups/$vnetResourceGroup/providers/Microsoft.Network/virtualNetworks/$vnetName"
$raw = & az network vnet show --subscription $subscriptionId --resource-group $vnetResourceGroup --name $vnetName --only-show-errors --output json 2>&1
if ($LASTEXITCODE -ne 0) { throw "Unable to read exact VNet inventory: $($raw -join ' '). No subnet existence flags were published." }
$vnet = ($raw -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
if ($vnet.id -ine $expectedId -or $vnet.subnets -isnot [Array]) {
    throw "Missing subnet inventory or VNet identity mismatch for '$expectedId'."
}
$names = @{}
foreach ($subnet in $vnet.subnets) {
    if ([string]::IsNullOrWhiteSpace($subnet.name) -or
        $subnet.id -ine "$expectedId/subnets/$($subnet.name)" -or $names.ContainsKey($subnet.name)) {
        throw 'Invalid, duplicate or foreign subnet inventory; no absence flags were published.'
    }
    $names[$subnet.name] = $true
}
$flags = [ordered]@{
    genai = 'sntGenaiExists'; aca = 'sntAcaExists'; 'aca-002' = 'sntAca002Exists'
    aks = 'sntAksExists'; 'aks-002' = 'sntAks002Exists'; webapp = 'sntWebappExists'
    dbxpriv = 'sntDatabricksPrivExists'; dbxpub = 'sntDatabricksPubExists'; logicapp = 'sntLogicappExists'
}
$needsLogicApp = Test-LogicAppPrivateIntegration $enableLogicApps $logicAppType $byoASEv3 $enablePublicAccessWithPerimeter
$state = [ordered]@{}
foreach ($purpose in $flags.Keys) {
    $name = "snt-prj$projectNumber-$purpose"
    $exists = $names.ContainsKey($name)
    if ($purpose -eq 'logicapp' -and $needsLogicApp -and $exists) {
        $env:AIFACTORY_USE_AZURE_CLI = 'true'
        $null = Get-ValidatedLogicAppSubnet -SubnetId "$expectedId/subnets/$name" -VnetId $expectedId
    }
    $state[$flags[$purpose]] = $exists.ToString().ToLowerInvariant()
}
foreach ($key in $state.Keys) {
    if ($env:GITHUB_ACTIONS -eq 'true') {
        "$key=$($state[$key])" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    } else {
        Write-Host "##vso[task.setvariable variable=$key]$($state[$key])"
    }
}
