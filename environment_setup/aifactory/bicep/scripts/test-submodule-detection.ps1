# Test script to verify submodule detection and parent repository handling
Write-Host "=== Testing Submodule Detection and Parent Repository Handling ===" -ForegroundColor Green

# Test current directory Git status
Write-Host "`n1. Checking current directory Git status..." -ForegroundColor Yellow
$currentLocation = Get-Location
Write-Host "Current location: $currentLocation"

# Check if .git is a file (submodule) or directory (main repo)
if (Test-Path ".git") {
    $gitType = Get-Item ".git"
    if ($gitType.PSIsContainer) {
        Write-Host "✓ This is a main Git repository (.git is a directory)" -ForegroundColor Green
    } else {
        Write-Host "✓ This is a Git submodule (.git is a file)" -ForegroundColor Cyan
        $gitContent = Get-Content ".git" -ErrorAction SilentlyContinue
        Write-Host "Git file content: $gitContent"
    }
} else {
    Write-Host "! No .git found in current directory" -ForegroundColor Yellow
}

# Test parent repository detection
Write-Host "`n2. Searching for parent repository..." -ForegroundColor Yellow
$searchPath = $currentLocation.Path
$parentFound = $false

while ($searchPath -and (Split-Path $searchPath -Parent)) {
    $parentPath = Split-Path $searchPath -Parent
    $parentGitPath = Join-Path $parentPath ".git"
    
    Write-Host "Checking: $parentPath"
    if (Test-Path $parentGitPath -PathType Container) {
        $gitConfigPath = Join-Path $parentGitPath "config"
        if (Test-Path $gitConfigPath) {
            Write-Host "✓ Found parent Git repository at: $parentPath" -ForegroundColor Green
            
            # Get parent repo URL
            Push-Location $parentPath
            $parentUrl = git remote get-url origin 2>&1
            Write-Host "Parent repository URL: $parentUrl"
            Pop-Location
            
            $parentFound = $true
            break
        }
    }
    $searchPath = $parentPath
}

if (-not $parentFound) {
    Write-Host "! No parent Git repository found" -ForegroundColor Yellow
}

# Test file path calculation
Write-Host "`n3. Testing file path calculation..." -ForegroundColor Yellow
$testFile = Join-Path $currentLocation "dynamicNetworkParams.json"
Write-Host "Test file path: $testFile"

if ($parentFound) {
    $relativePath = $testFile.Replace($parentPath, "").TrimStart('\', '/')
    $relativePath = $relativePath.Replace('\', '/')
    Write-Host "Relative path from parent repo: $relativePath"
}

Write-Host "`n=== Summary ===" -ForegroundColor Green
Write-Host "Current directory: $(if (Test-Path '.git') { if ((Get-Item '.git').PSIsContainer) { 'Main Git Repo' } else { 'Git Submodule' } } else { 'Not a Git directory' })"
Write-Host "Parent repository: $(if ($parentFound) { 'Found' } else { 'Not found' })"
Write-Host "Ready for enhanced Git operations: $(if ($parentFound -or (Test-Path '.git' -PathType Container)) { 'Yes' } else { 'No' })"
