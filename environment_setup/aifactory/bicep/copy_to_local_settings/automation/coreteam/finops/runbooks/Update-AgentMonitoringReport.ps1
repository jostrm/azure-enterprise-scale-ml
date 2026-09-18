<#
.SYNOPSIS
    Offline opt-in agent BUSINESS VALUE + COST + SECURITY report over reviewed observations.
.DESCRIPTION
    No Azure login, collection, publishing, schedule or upload. All selects all authorized
    collected rows, then all five selectors intersect before totals/charts/exports.
    Python 3 standard library only. Use samples/agent-observations.sample.json for local proof.
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
    [string]$AuthorizedScopesPath,
    [string]$OutputPath,
    [string]$CsvPath,
    [string]$CanonicalObservationsPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script = Join-Path $PSScriptRoot '..\..\..\native_monitoring.py'
$arguments = @('-I', '-B', $script, '--input', $ObservationsPath, '--aiFactory', $AiFactory,
    '--scaleset', $Scaleset, '--project', $Project, '--environment', $Environment, '--agent', $Agent)
if ($OutputPath) { $arguments += @('--output', $OutputPath) }
if ($CsvPath) { $arguments += @('--csv', $CsvPath) }
if ($CanonicalObservationsPath) { $arguments += @('--observations-output', $CanonicalObservationsPath) }
if ($Source) { $arguments += @('--source', $Source.ToLowerInvariant()) }
if ($AuthorizedScopesPath) { $arguments += @('--authorized-scopes', $AuthorizedScopesPath) }
& $Python @arguments
exit $LASTEXITCODE
