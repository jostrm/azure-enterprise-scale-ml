$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'modules/logicAppSubnet.ps1')

# Older ADO variable files do not contain logicAppType or the optional BYO name.
# Read exported variables rather than interpreting an unexpanded $(...) as a value.
$defaults = @{
    enableLogicApps = 'false'; logicAppType = 'Standard'
    byoASEv3 = 'false'; enablePublicAccessWithPerimeter = 'false'
    subnetProjLogicapp = ''
}
$values = @{}
foreach ($name in $defaults.Keys) {
    $value = [Environment]::GetEnvironmentVariable($name.ToUpperInvariant())
    if ([string]::IsNullOrEmpty($value)) { $value = $defaults[$name] }
    $values[$name] = $value
}
$null = Test-LogicAppSubnetRequired $values.enableLogicApps $values.logicAppType $values.byoASEv3 $values.enablePublicAccessWithPerimeter
foreach ($name in $values.Keys) {
    if ($values[$name] -match '\$\(|[\r\n]') { throw "Unresolved or invalid $name." }
    Write-Host "##vso[task.setvariable variable=$name]$($values[$name])"
}
