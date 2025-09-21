# Comprehensive script to fix all remaining diagnostic settings retentionPolicy issues
$bicepFiles = Get-ChildItem -Path . -Recurse -Filter "*.bicep" | Where-Object { $_.Name -notlike "*test*" }

Write-Host "Searching for remaining retentionPolicy issues in diagnostic settings..."

$filesToFix = @()
foreach ($file in $bicepFiles) {
    $content = Get-Content -Path $file.FullName -Raw
    if ($content -match 'Microsoft\.Insights/diagnosticSettings.*retentionPolicy') {
        $filesToFix += $file
        Write-Host "Found diagnostic retentionPolicy in: $($file.FullName)"
    }
}

if ($filesToFix.Count -eq 0) {
    Write-Host "✅ No remaining diagnostic retentionPolicy issues found!"
} else {
    Write-Host "`nFound $($filesToFix.Count) files with diagnostic retentionPolicy issues."
}
