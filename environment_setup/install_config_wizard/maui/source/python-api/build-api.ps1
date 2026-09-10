param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot "dist"),
    [string]$WorkRoot = (Join-Path $PSScriptRoot "build\api"),
    [string]$Python = "python",
    [switch]$SkipRestore
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not $SkipRestore) {
    & $Python -m pip install --quiet --upgrade -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency restore failed."
    }
}

Push-Location $root
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $OutputRoot `
        --workpath $WorkRoot `
        (Join-Path $root "aifactory-api.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "FastAPI sidecar build failed."
    }
}
finally {
    Pop-Location
}

$executable = Join-Path $OutputRoot "aifactory-api\aifactory-api.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "FastAPI sidecar executable was not created."
}

$workerHelp = & $executable --catalog-worker --help 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $workerHelp -notmatch "--protected-manifest" -or $workerHelp -notmatch "--execution-root") {
    throw "The bundled catalog worker smoke check failed."
}

Write-Host "FastAPI sidecar: $executable" -ForegroundColor Green
