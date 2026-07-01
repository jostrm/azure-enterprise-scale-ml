Import-Module "$PSScriptRoot/common/AifFactory.psm1" -Force
$out = pwsh -NoProfile -File "$PSScriptRoot/Update-FoundryTokenReport.ps1" -Source github -UseCurrentLogin 2>&1 | Out-String
$lines = $out -split "`r?`n"
$start = ($lines | Select-String -Pattern '^# ' | Select-Object -First 1).LineNumber - 1
$md = ($lines[$start..($lines.Count-1)] -join "`n")
$base = "foundry-token-report-{0:yyyyMMdd}" -f (Get-Date)
$files = Export-ReportFiles -Markdown $md -BaseName $base -OutDir (Join-Path $PSScriptRoot 'reports-out')
$files | Format-List
if ($files.Pdf) { Start-Process $files.Pdf }
