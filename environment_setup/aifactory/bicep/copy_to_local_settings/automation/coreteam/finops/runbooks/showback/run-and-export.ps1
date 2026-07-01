# Local preview: run the showback runbook and export MD/HTML/PDF to ./reports-out.
# DryRun uses sample data from report-config.json (no Azure calls). Drop -DryRun and add
# -UseCurrentLogin -SubscriptionId <sub> (and -Source github|ado) to run against real cost data.
param(
    [switch]$Live,
    [ValidateSet('github','ado','config')] [string]$Source = 'config',
    [string]$SubscriptionId,
    [string]$SettingsPath
)

$ErrorActionPreference = 'Stop'
$outDir = Join-Path $PSScriptRoot 'reports-out'

$common = @{ Source = $Source; OutDir = $outDir }
if ($Live) {
    $common['UseCurrentLogin'] = $true
    if ($SubscriptionId) { $common['SubscriptionId'] = $SubscriptionId }
    if ($SettingsPath)   { $common['SettingsPath']   = $SettingsPath }
} else {
    $common['DryRun'] = $true
}

& "$PSScriptRoot/Update-ShowbackReport.ps1" @common

$base = "aifactory-showback-*-{0:yyyyMMdd}" -f (Get-Date)
$pdf = Get-ChildItem -Path $outDir -Filter "$base.pdf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($pdf) { Start-Process $pdf.FullName }
