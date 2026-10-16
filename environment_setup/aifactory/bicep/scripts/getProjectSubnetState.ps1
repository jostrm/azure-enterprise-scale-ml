param(
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [Parameter(Mandatory = $true)][string]$ResourceGroupName,
    [Parameter(Mandatory = $true)][string]$VnetName,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{3}$')][string]$ProjectNumber,
    [ValidateSet('ado', 'github')][string]$Provider = 'ado'
)
$ErrorActionPreference = 'Stop'
$expectedId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Network/virtualNetworks/$VnetName"
$response = & az network vnet show --subscription $SubscriptionId --resource-group $ResourceGroupName --name $VnetName --only-show-errors --output json 2>&1
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the selected VNet; no subnet absence flags were published.' }
$vnet = ($response -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
if ($vnet.Id -ine $expectedId -or $vnet.Subnets -isnot [System.Collections.IList]) {
    throw 'VNet response must match the requested scope and contain a complete subnet array.'
}
$names = @{}
foreach ($subnet in $vnet.Subnets) {
    if ([string]::IsNullOrWhiteSpace($subnet.Name) -or $subnet.Id -ine "$expectedId/subnets/$($subnet.Name)" -or $names.ContainsKey($subnet.Name)) {
        throw 'Invalid, duplicate or foreign subnet inventory; no absence flags were published.'
    }
    $names[$subnet.Name] = $true
}
$purposes = [ordered]@{
    genai='sntGenaiExists'; aca='sntAcaExists'; 'aca-002'='sntAca002Exists'
    aks='sntAksExists'; 'aks-002'='sntAks002Exists'; webapp='sntWebappExists'
    logicapp='sntLogicappExists'; dbxpriv='sntDatabricksPrivExists'; dbxpub='sntDatabricksPubExists'
}
if ($Provider -eq 'github' -and [string]::IsNullOrWhiteSpace($env:GITHUB_ENV)) {
    throw 'GITHUB_ENV is required to publish subnet state.'
}
foreach ($entry in $purposes.GetEnumerator()) {
    $exists = $names.ContainsKey("snt-prj$ProjectNumber-$($entry.Key)").ToString().ToLowerInvariant()
    if ($Provider -eq 'ado') {
        Write-Host "##vso[task.setvariable variable=$($entry.Value)]$exists"
    } else {
        Add-Content -LiteralPath $env:GITHUB_ENV -Value "$($entry.Value)=$exists" -Encoding utf8
    }
}
