# PowerShell script to fix diagnostic settings by removing retentionPolicy from all Bicep files
# This fixes the Azure error: "Diagnostic settings does not support retention for new diagnostic settings"

$diagnosticsPath = "environment_setup\aifactory\bicep\modules\diagnostics"
$bicepFiles = Get-ChildItem -Path $diagnosticsPath -Filter "*.bicep"

Write-Host "Found $($bicepFiles.Count) diagnostic Bicep files to process..."

foreach ($file in $bicepFiles) {
    Write-Host "Processing: $($file.Name)"
    
    $content = Get-Content -Path $file.FullName -Raw
    
    # Remove all retentionPolicy blocks using regex
    # This pattern matches the entire retentionPolicy block including whitespace and braces
    $pattern = '\s*retentionPolicy:\s*\{\s*enabled:\s*(true|false)\s*days:\s*\d+\s*\}'
    $updatedContent = $content -replace $pattern, ''
    
    # Also clean up any extra whitespace that might be left
    $updatedContent = $updatedContent -replace '\n\s*\n\s*\n', "`n`n"
    
    # Write the updated content back to the file
    Set-Content -Path $file.FullName -Value $updatedContent -NoNewline
    
    Write-Host "  ✓ Updated $($file.Name)"
}

Write-Host "`n✅ All diagnostic modules have been updated to remove retentionPolicy!"
Write-Host "The Azure diagnostic settings error should now be resolved."