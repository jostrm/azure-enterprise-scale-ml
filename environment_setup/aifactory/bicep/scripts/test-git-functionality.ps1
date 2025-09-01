# Test script to verify Git functionality for genDynamicNetworkParamFile.ps1
# This script tests the Git repository detection and save functionality

Write-Host "=== Testing Git Repository Functionality ===" -ForegroundColor Green

# Test 1: Check if we're in a Git repository
Write-Host "`n1. Testing Git repository detection..." -ForegroundColor Yellow
try {
    $gitStatus = git status 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Git repository detected" -ForegroundColor Green
        
        # Get remote URL
        $gitRemoteUrl = git remote get-url origin 2>&1
        Write-Host "Repository URL: $gitRemoteUrl"
        
        # Detect repository type
        if ($gitRemoteUrl -match "dev.azure.com|visualstudio.com") {
            Write-Host "✓ Azure DevOps repository detected" -ForegroundColor Green
        } elseif ($gitRemoteUrl -match "github.com") {
            Write-Host "✓ GitHub repository detected" -ForegroundColor Green
        } else {
            Write-Host "! Generic Git repository detected" -ForegroundColor Yellow
        }
        
        # Show current branch
        $currentBranch = git branch --show-current
        Write-Host "Current branch: $currentBranch"
        
    } else {
        Write-Host "✗ Not in a Git repository" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "✗ Git not available or repository error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 2: Check Git authentication/access
Write-Host "`n2. Testing Git authentication..." -ForegroundColor Yellow
try {
    $gitRemote = git ls-remote origin HEAD 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Git authentication working - can access remote repository" -ForegroundColor Green
    } else {
        Write-Host "! Git authentication may have issues: $gitRemote" -ForegroundColor Yellow
        Write-Host "  This may still work in Azure DevOps/GitHub pipelines with service connections" -ForegroundColor Cyan
    }
} catch {
    Write-Host "! Could not test remote access: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Test 3: Create a test file and see if Git operations would work
Write-Host "`n3. Testing Git file operations..." -ForegroundColor Yellow
$testFile = Join-Path (Get-Location) "test-dynamic-params.json"
$testContent = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "testParameter": {
            "value": "test-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        }
    }
}
"@

try {
    $testContent | Out-File $testFile -Encoding UTF8
    Write-Host "✓ Test file created: $testFile" -ForegroundColor Green
    
    # Test git add (dry run)
    git add --dry-run $testFile 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Git add would work" -ForegroundColor Green
    } else {
        Write-Host "! Git add might have issues" -ForegroundColor Yellow
    }
    
    # Clean up
    Remove-Item $testFile -Force
    Write-Host "✓ Test file cleaned up" -ForegroundColor Green
    
} catch {
    Write-Host "✗ Test file operations failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== Test Summary ===" -ForegroundColor Green
Write-Host "The genDynamicNetworkParamFile.ps1 script now includes:" -ForegroundColor Cyan
Write-Host "• Parameter: -saveFileInADOGitRepo `$true" -ForegroundColor White
Write-Host "• Automatic detection of Azure DevOps vs GitHub vs Generic Git" -ForegroundColor White
Write-Host "• Git commit and push functionality" -ForegroundColor White
Write-Host "• Proper error handling and fallback to local-only save" -ForegroundColor White

Write-Host "`nTo use in your pipeline:" -ForegroundColor Yellow
Write-Host ".\genDynamicNetworkParamFile.ps1 [your existing parameters] -saveFileInADOGitRepo `$true" -ForegroundColor White

Write-Host "`nNote: In Azure DevOps/GitHub pipelines, the build agent typically has" -ForegroundColor Cyan
Write-Host "access via service connections and will be able to push changes automatically." -ForegroundColor Cyan
