<#
.SYNOPSIS
    Offline opt-in six-family usage, value, cost, reliability and security evidence report.
.DESCRIPTION
    No Azure login, collection, publishing, schedule or upload. All selects all authorized
    collected rows, then all five selectors intersect before totals/charts/exports.
    Python 3 standard library only. Use samples/monitoring-observations.six-reports.sample.json
    with -Source sample -NativeVersion 2 for six-family local proof; native v1 remains supported.
#>
param(
    [Parameter(Mandatory)] [string]$ObservationsPath,
    [string]$Python = 'python',
    [string]$AiFactory = 'All',
    [string]$Scaleset = 'All',
    [string]$Project = 'All',
    [string]$Environment = 'All',
    [string]$Agent = 'All',
    [ValidateSet('sample','live')] [string]$Source,
    [ValidateSet(1,2)] [Nullable[int]]$NativeVersion,
    [string]$AuthorizedScopesPath,
    [string]$OutputPath,
    [string]$CsvPath,
    [string]$CanonicalObservationsPath,
    [string]$NativeObservationsPath,
    [string]$EventsPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script = Join-Path $PSScriptRoot '..\..\..\native_monitoring.py'
$arguments = @('-I', '-B', $script, '--input', $ObservationsPath, '--aiFactory', $AiFactory,
    '--scaleset', $Scaleset, '--project', $Project, '--environment', $Environment, '--agent', $Agent)
if ($null -ne $NativeVersion) { $arguments += @('--native-version', $NativeVersion) }
if ($OutputPath) { $arguments += @('--output', $OutputPath) }
if ($CsvPath) { $arguments += @('--csv', $CsvPath) }
if ($CanonicalObservationsPath) { $arguments += @('--observations-output', $CanonicalObservationsPath) }
if ($NativeObservationsPath) { $arguments += @('--native-output', $NativeObservationsPath) }
if ($EventsPath) { $arguments += @('--events', $EventsPath) }
if ($Source) { $arguments += @('--source', $Source.ToLowerInvariant()) }
if ($AuthorizedScopesPath) { $arguments += @('--authorized-scopes', $AuthorizedScopesPath) }
& $Python @arguments
exit $LASTEXITCODE
