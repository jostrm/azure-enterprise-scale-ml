<#
.SYNOPSIS
    Safe local consumer example. Prints Project001-only sample report; no Azure calls or files.
.EXAMPLE
    pwsh -NoProfile -File .\run-native-monitoring-sample.ps1
.EXAMPLE
    pwsh -NoProfile -File .\run-native-monitoring-sample.ps1 -Project All
#>
param([string]$Python = 'python', [string]$Project = '001')
$ErrorActionPreference = 'Stop'
& $Python -I -B (Join-Path $PSScriptRoot 'native_monitoring.py') `
    --input (Join-Path $PSScriptRoot 'samples\agent-observations.sample.json') `
    --aiFactory factory-a --scaleset 001 --project $Project
exit $LASTEXITCODE
