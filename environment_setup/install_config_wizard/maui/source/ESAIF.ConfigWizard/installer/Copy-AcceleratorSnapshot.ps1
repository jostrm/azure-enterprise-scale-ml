param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination
)
$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath $Source).Path
$destinationRoot = [IO.Path]::GetFullPath($Destination)
if ($destinationRoot.StartsWith($sourceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $sourceRoot.StartsWith($destinationRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $sourceRoot -eq $destinationRoot) {
    throw "The audited snapshot and staging directory must be separate, non-nested directories."
}
if (-not (Test-Path (Join-Path $sourceRoot "bootstrap\GHA-create-new-aifactory-scaleset.sh"))) {
    throw "Snapshot is missing the required Simple Mode bootstrap."
}
# A prepared snapshot may include clean Git object metadata, never a developer's checkout credentials.
$entries = @(Get-ChildItem -LiteralPath $sourceRoot -Force -Recurse)
foreach ($entry in $entries) {
    $relative = [IO.Path]::GetRelativePath($sourceRoot, $entry.FullName)
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Snapshot contains a link: $relative" }
    if ($relative -match '(^|\\)(bin|obj|node_modules|__pycache__|\.venv|saved-projects|\.azure|\.ssh)(\\|$)' -or
        $relative -match '^environment_setup\\install_config_wizard(\\|$)' -or
        ($relative -match '(^|\\)\.env(\..*)?$' -and
            $relative -ne 'environment_setup\aifactory\bicep\copy_to_local_settings\github-actions\.env.template') -or
        $relative -match '(^|\\)(id_rsa|id_ed25519|credentials|operations\.db)$' -or
        $relative -match '\.(pfx|p12|pem|key)$') {
        throw "Snapshot is not sanitized: $relative"
    }
    if (-not $entry.PSIsContainer -and $relative -eq '.git\config') {
        $config = Get-Content $entry.FullName -Raw
        if ($config -match '(?im)^\s*\[\s*(include|includeIf|credential|http|url|filter|alias)\b|https?://[^/\s]+@|^\s*(hooksPath|fsmonitor|sshCommand)\s*=') {
            throw "Snapshot Git configuration contains credentials or executable configuration."
        }
    }
}
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
Get-ChildItem -LiteralPath $sourceRoot -Force | Copy-Item -Destination $destinationRoot -Recurse -Force
