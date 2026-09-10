[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceReposRoot,
    [Parameter(Mandatory)][string]$ApiSource,
    [string]$Destination = (Join-Path $PSScriptRoot "source")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (Test-Path -LiteralPath $Destination) {
    throw "Export destination already exists. Choose an empty destination to avoid overwriting source changes: $Destination"
}

$entries = [System.Collections.Generic.List[object]]::new()
$excludedDirectories = @("bin", "obj", ".vs", ".git", "artifacts", "__pycache__", ".pytest_cache", ".venv", "node_modules", "history")

function Copy-SourceFile([string]$File, [string]$RelativePath) {
    $target = Join-Path $Destination $RelativePath
    $before = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $File -Destination $target
    $copied = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if ($before -ne $copied -or $before -ne (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash) {
        throw "Source changed during export; retry with a fresh destination: $RelativePath"
    }
    $entries.Add([ordered]@{ path = $RelativePath.Replace("\", "/"); sha256 = $copied.ToLowerInvariant() })
}

function Copy-SourceTree([string]$Root, [string]$RelativePath) {
    foreach ($item in Get-ChildItem -LiteralPath $Root -Force) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Source exports do not follow links: $($item.FullName)"
        }
        if ($item.PSIsContainer) {
            if ($item.Name -notin $excludedDirectories) {
                Copy-SourceTree $item.FullName (Join-Path $RelativePath $item.Name)
            }
        }
        elseif ($item.Extension -notin @(".pyc", ".pdb", ".user") -and $item.Name -ne ".env") {
            Copy-SourceFile $item.FullName (Join-Path $RelativePath $item.Name)
        }
    }
}

foreach ($project in @("ESAIF.ConfigWizard", "ESAIF.BaseLayer", "ESAIF.DomainLayer")) {
    $root = Join-Path $SourceReposRoot $project
    foreach ($directory in @("src", "tests")) {
        Copy-SourceTree (Join-Path $root $directory) (Join-Path $project $directory)
    }
    foreach ($directory in @("tools", "installer")) {
        if (Test-Path -LiteralPath (Join-Path $root $directory)) {
            Copy-SourceTree (Join-Path $root $directory) (Join-Path $project $directory)
        }
    }
    foreach ($file in Get-ChildItem -LiteralPath $root -File -Force) {
        if ($file.Extension -in @(".slnx", ".ps1") -or $file.Name -eq ".gitignore") {
            Copy-SourceFile $file.FullName (Join-Path $project $file.Name)
        }
    }
}

foreach ($directory in @("src", "tests", "template-files")) {
    Copy-SourceTree (Join-Path $ApiSource $directory) (Join-Path "python-api" $directory)
}
Copy-SourceFile (Join-Path $ApiSource "template-files\.env") "python-api\template-files\.env"
foreach ($name in @("requirements.txt", "requirements-dev.txt", "build-api.ps1", "aifactory-api.spec", ".gitignore")) {
    Copy-SourceFile (Join-Path $ApiSource $name) (Join-Path "python-api" $name)
}
Copy-SourceFile (Join-Path $ApiSource "docs\openapi.json") "python-api\docs\openapi.json"

$manifest = [ordered]@{
    schemaVersion = 1
    description = "Buildable MAUI application and Python API source snapshot; excludes developer outputs and saved configuration."
    files = @($entries | Sort-Object { $_.path })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Destination "source-manifest.json") -Encoding utf8
Write-Host "Exported $($entries.Count) files to $Destination"
