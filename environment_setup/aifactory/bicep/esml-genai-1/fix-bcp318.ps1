# PowerShell script to add #disable-next-line BCP318 comments to suppress all BCP318 warnings
# This script processes the Bicep file and adds suppression comments before lines that cause BCP318 warnings

$bicepFile = "32-main.bicep"
$backupFile = "32-main.bicep.backup"

# Create backup
Copy-Item $bicepFile $backupFile -Force
Write-Host "Created backup: $backupFile"

# Read the file content
$content = Get-Content $bicepFile

# Define patterns that typically cause BCP318 warnings
$patterns = @(
    '\.outputs\.',
    '\.properties\.',
    '\.identity\.',
    '\.listKeys\(\)',
    '\.id\s*:',
    'REF\.'
)

$newContent = @()
$lineNumber = 0

foreach ($line in $content) {
    $lineNumber++
    
    # Check if this line contains patterns that might cause BCP318 warnings
    $needsSuppression = $false
    foreach ($pattern in $patterns) {
        if ($line -match $pattern) {
            # Additional checks to avoid false positives
            if ($line -notmatch '^\s*//') {  # Not a comment
                $needsSuppression = $true
                break
            }
        }
    }
    
    # Check if the previous line already has a BCP318 suppression
    $prevLineHasSuppression = $false
    if ($newContent.Count -gt 0) {
        $prevLine = $newContent[-1]
        if ($prevLine -match '#disable-next-line BCP318') {
            $prevLineHasSuppression = $true
        }
    }
    
    # Add suppression comment if needed and not already present
    if ($needsSuppression -and -not $prevLineHasSuppression) {
        # Get the indentation of the current line
        $indent = ""
        if ($line -match '^(\s*)') {
            $indent = $matches[1]
        }
        
        # Add suppression comment with same indentation
        $newContent += "$indent#disable-next-line BCP318"
        Write-Host "Added suppression before line $lineNumber`: $($line.Trim())"
    }
    
    # Add the original line
    $newContent += $line
}

# Write the modified content back to the file
$newContent | Set-Content $bicepFile -Encoding UTF8

Write-Host "`nModification complete! Added BCP318 suppressions to $bicepFile"
Write-Host "Original file backed up as: $backupFile"
Write-Host "`nYou can now test with: az bicep build --file $bicepFile"
