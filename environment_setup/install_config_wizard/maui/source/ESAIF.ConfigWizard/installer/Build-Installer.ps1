param(
    [Parameter(Mandatory)][string]$PublishDirectory,
    [ValidatePattern('^\d+\.\d+\.\d+(\.\d+)?$')][string]$Version = "1.0.0",
    [string]$Compiler,
    [string]$AppId = "{A6B3C23C-9718-4E61-8CE5-823EAB0E5BCD}",
    [string]$OutputDirectory
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root "artifacts\installer" }
if (-not $Compiler) { $Compiler = & (Join-Path $PSScriptRoot "Get-InnoCompiler.ps1") }
$icon = Get-ChildItem (Join-Path $root "src\ESAIF.ConfigWizard\obj\Release") -Recurse -Filter appicon.ico |
    Where-Object FullName -Match 'win-x64' | Select-Object -First 1 -ExpandProperty FullName
if (-not $icon) { throw "The Release MAUI application icon has not been generated." }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$staging = Join-Path ([IO.Path]::GetTempPath()) ("aif-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    # Inno Setup 6 cannot read the accelerator's deep paths in a nested source checkout.
    Copy-Item -LiteralPath $PublishDirectory -Destination (Join-Path $staging "payload") -Recurse
    Copy-Item -LiteralPath $icon -Destination (Join-Path $staging "app.ico")
    & $Compiler /Qp "/DPayload=$staging\payload" "/DAppVersion=$Version" "/DAppIcon=$staging\app.ico" "/DProductId=$AppId" "/O$OutputDirectory" (Join-Path $PSScriptRoot "ESAIF.ConfigWizard.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
}
finally {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
$files = @(Get-ChildItem $OutputDirectory -File | Where-Object Name -Match "^ESAIF\.ConfigWizard-$([regex]::Escape($Version))-win-x64-setup.*\.(exe|bin)$")
if (-not ($files | Where-Object Extension -eq '.exe')) { throw "Setup executable missing." }
if ($files | Where-Object Length -GE 100MB) { throw "Installer contains a file exceeding the GitHub 100 MiB limit." }
$files | ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())  $($_.Name)" } |
    Set-Content (Join-Path $OutputDirectory "SHA256SUMS.txt") -Encoding utf8
Copy-Item (Join-Path $PSScriptRoot "SUPPORT.txt") $OutputDirectory -Force
$files | Select-Object Name, Length
Write-Host "Installer output: $OutputDirectory" -ForegroundColor Green
