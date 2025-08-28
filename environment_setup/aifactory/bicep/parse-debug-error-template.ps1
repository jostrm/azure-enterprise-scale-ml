# Parse debug.md file and extract error information
param(
    [string]$DebugFilePath = ".\debug.md"
)

# Read the debug file content
$content = Get-Content -Path $DebugFilePath -Raw

# Initialize array to store parsed errors
$errors = @()

# Split content by lines for processing
$lines = $content -split "`n"

# Extract deployment name from first line
$deploymentName = ""
if ($lines[0] -match "^(.+)$") {
    $deploymentName = $lines[0].Trim()
}

# Define regex patterns for extracting information
$patterns = @{
    Code = "Code:\s*(\w+)"
    BicepModule = "Microsoft\.Resources/deployments/([^/\s]+)"
    ResourceName = "Microsoft\.Authorization/roleAssignments/([a-f0-9-]+)"
    Message = "Message:\s*(.+?)(?=\s+Code:|$)"
}

# Process each line to extract error information
$currentError = @{}

foreach ($line in $lines) {
    $line = $line.Trim()
    
    # Skip empty lines
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    
    # Extract error codes
    if ($line -match $patterns.Code) {
        $errorCode = $matches[1]
        
        # If we already have an error being processed, add it to the collection
        if ($currentError.Count -gt 0) {
            $errors += [PSCustomObject]$currentError
        }
        
        # Start new error
        $currentError = @{
            ErrorCode = $errorCode
            BicepModule = ""
            Deployment = $deploymentName
            ResourceName = ""
            Message = ""
        }
    }
    
    # Extract bicep module/deployment names
    if ($line -match $patterns.BicepModule) {
        $moduleName = $matches[1]
        if ($currentError.ContainsKey('ErrorCode')) {
            $currentError.BicepModule = $moduleName
        }
    }
    
    # Extract resource names (role assignment GUIDs)
    if ($line -match $patterns.ResourceName) {
        $resourceName = $matches[1]
        if ($currentError.ContainsKey('ErrorCode')) {
            $currentError.ResourceName = $resourceName
        }
    }
    
    # Extract error messages
    if ($line -match "Message:\s*(.+?)$") {
        $message = $matches[1].Trim()
        if ($currentError.ContainsKey('ErrorCode')) {
            $currentError.Message = $message
        }
    }
}

# Add the last error if exists
if ($currentError.Count -gt 0) {
    $errors += [PSCustomObject]$currentError
}

# Clean up and deduplicate errors
$uniqueErrors = $errors | Where-Object { $_.ErrorCode -ne "" } | Sort-Object ErrorCode, BicepModule -Unique

Write-Host "=====================================================================================================" -ForegroundColor Cyan
Write-Host "🔍 BICEP DEPLOYMENT ERROR ANALYSIS" -ForegroundColor Yellow  
Write-Host "=====================================================================================================" -ForegroundColor Cyan
Write-Host ""

$lines = Get-Content $DebugFilePath
$deploymentErrors = @()
$issueCount = 0

# Simple parsing approach
$currentDeployment = ""
$currentErrorCodes = @()
$currentMessages = @()
$currentExceptions = @()

foreach ($line in $lines) {
    # Find deployment names
    if ($line -match "05-\w+") {
        $currentDeployment = $matches[0]
    }
    if ($line -match "Target:.*deployments/([^\s]+)") {
        $currentDeployment = $matches[1]
    }
    
    # Find error codes
    if ($line -match "Code:\s*(\w+)") {
        $code = $matches[1]
        if ($currentErrorCodes -notcontains $code) {
            $currentErrorCodes += $code
        }
    }
    
    # Find messages
    if ($line -match "Message:\s*(.+)") {
        $msg = $matches[1].Trim()
        if ($msg.Length -lt 100) {
            $currentMessages += $msg
        }
    }
    
    # Find exception details
    if ($line -match "Exception Details.*\((\w+)\)\s*(.+)") {
        $exCode = $matches[1]
        $exMsg = $matches[2].Trim()
        $currentExceptions += "$exCode : $exMsg"
    }
}

# Create summary
if ($currentErrorCodes.Count -gt 0 -or $currentMessages.Count -gt 0 -or $currentExceptions.Count -gt 0) {
    $issueCount++
    
    $errorObj = [PSCustomObject]@{
        IssueNumber = $issueCount
        DeploymentName = if ($currentDeployment) { $currentDeployment } else { "esml-p001-dev-eus2--001-001-65-compute-services" }
        ErrorCodes = ($currentErrorCodes -join ", ")
        Messages = ($currentMessages -join " | ")
        ExceptionDetails = ($currentExceptions -join " | ")
        Severity = if ($currentErrorCodes -contains "RoleAssignmentExists") { "Medium" } else { "High" }
    }
    
    $deploymentErrors += $errorObj
}

if ($deploymentErrors.Count -eq 0) {
    Write-Host "✅ No deployment errors found in the debug file." -ForegroundColor Green
    return
}

Write-Host "📊 SUMMARY: Found $($deploymentErrors.Count) deployment error(s)" -ForegroundColor Yellow
Write-Host ""

foreach ($errorItem in $deploymentErrors) {
    $severityColor = if ($errorItem.Severity -eq "High") { "Red" } else { "Yellow" }
    
    Write-Host "🚨 ISSUE [$($errorItem.IssueNumber)]" -ForegroundColor $severityColor
    Write-Host "   📍 Deployment: $($errorItem.DeploymentName)" -ForegroundColor White
    Write-Host "   📋 Error Code(s): $($errorItem.ErrorCodes)" -ForegroundColor White
    
    if ($errorItem.Messages) {
        Write-Host "   💬 Message(s): $($errorItem.Messages)" -ForegroundColor Gray
    }
    
    if ($errorItem.ExceptionDetails) {
        Write-Host "   🔍 Exception(s): $($errorItem.ExceptionDetails)" -ForegroundColor Cyan
    }
    
    Write-Host "   ⚠️  Severity: $($errorItem.Severity)" -ForegroundColor $severityColor
    Write-Host ""
}

Write-Host "=====================================================================================================" -ForegroundColor Cyan
Write-Host "🎯 KEY ISSUES IDENTIFIED:" -ForegroundColor Yellow
Write-Host "=====================================================================================================" -ForegroundColor Cyan

if ($uniqueErrors.Count -gt 0) {
    
    # ===============================
    # KEY ISSUES ANALYSIS
    # ===============================
    Write-Host ""
    
    $duplicateResources = $uniqueErrors | Where-Object { $_.Message -like "*defined multiple times*" }
    $existingRoles = $uniqueErrors | Where-Object { $_.ErrorCode -eq "RoleAssignmentExists" }
    $miRbacModules = $uniqueErrors | Where-Object { $_.BicepModule -like "*miRbac*" -or $_.BicepModule -like "*miPrjRbac*" }
    
    $issueNumber = 1
    
    if ($duplicateResources.Count -gt 0) {
        Write-Host "  $issueNumber. DUPLICATE RESOURCE DEFINITIONS" -ForegroundColor Red
        Write-Host "     Problem: Role assignment GUIDs are not unique" -ForegroundColor Yellow
        Write-Host "     Affected Resources:" -ForegroundColor Yellow
        foreach ($dup in $duplicateResources) {
            if ($dup.ResourceName) {
                Write-Host "       * $($dup.ResourceName)" -ForegroundColor White
            }
        }
        Write-Host "     Modules: miRbacCmnACR, miPrjRbacCmnACR" -ForegroundColor Yellow
        Write-Host "     Root Cause: guid() function generates same GUID for multiple managed identities" -ForegroundColor Yellow
        Write-Host ""
        $issueNumber++
    }
    
    if ($existingRoles.Count -gt 0) {
        Write-Host "  $issueNumber. ROLE ASSIGNMENT CONFLICTS" -ForegroundColor Red
        Write-Host "     Problem: Attempting to create already existing role assignments" -ForegroundColor Yellow
        Write-Host "     Error Code: RoleAssignmentExists" -ForegroundColor Yellow
        Write-Host "     Affected Modules:" -ForegroundColor Yellow
        $existingRoles | ForEach-Object { 
            if ($_.BicepModule) {
                Write-Host "       * $($_.BicepModule)" -ForegroundColor White
            }
        }
        Write-Host "     Root Cause: Role assignments created in previous deployments" -ForegroundColor Yellow
        Write-Host ""
        $issueNumber++
    }
    
    if ($miRbacModules.Count -gt 0) {
        Write-Host "  $issueNumber. MIRBAC MODULE GUID CONFLICTS" -ForegroundColor Red
        Write-Host "     Problem: Multiple miRbac calls with identical GUID generation" -ForegroundColor Yellow
        Write-Host "     Affected Deployments:" -ForegroundColor Yellow
        $miRbacModules | ForEach-Object {
            if ($_.BicepModule) {
                Write-Host "       * $($_.BicepModule)" -ForegroundColor White
            }
        }
        Write-Host "     Root Cause: GUID function doesn't include container registry name" -ForegroundColor Yellow
        Write-Host ""
    }
    
    # ===============================
    # RECOMMENDATIONS
    # ===============================
    Write-Host ""
    Write-Host "=====================================================================================================" -ForegroundColor Cyan
    Write-Host "💡 RECOMMENDATIONS:" -ForegroundColor Green
    Write-Host "=====================================================================================================" -ForegroundColor Cyan
    Write-Host ""
    
    $recNumber = 1
    
    if ($duplicateResources.Count -gt 0 -or $miRbacModules.Count -gt 0) {
        Write-Host "  $recNumber. FIX GUID GENERATION IN miRbac.bicep" -ForegroundColor Green
        Write-Host "     Current: guid(deployment().name, principalId)" -ForegroundColor Yellow
        Write-Host "     Recommended: guid(containerRegistryName, principalId)" -ForegroundColor Cyan
        Write-Host "     Benefits: Ensures unique GUIDs per container registry + principal combination" -ForegroundColor White
        Write-Host "     Impact: Prevents duplicate role assignment resource definitions" -ForegroundColor White
        Write-Host ""
        $recNumber++
    }
    
    if ($existingRoles.Count -gt 0) {
        Write-Host "  $recNumber. IMPLEMENT IDEMPOTENT ROLE ASSIGNMENTS" -ForegroundColor Green
        Write-Host "     Add condition: Check if role assignment already exists" -ForegroundColor Cyan
        Write-Host "     Use existing check: Create helper module to detect existing assignments" -ForegroundColor White
        Write-Host "     Fallback: Use try-catch in deployment scripts" -ForegroundColor White
        Write-Host ""
        $recNumber++
    }
    
    Write-Host "  $recNumber. IMMEDIATE ACTION REQUIRED" -ForegroundColor Green
    Write-Host "     File to modify: modules/miRbac.bicep" -ForegroundColor Cyan
    Write-Host "     Change line: guid() function call" -ForegroundColor Yellow
    Write-Host "     Test: Re-run deployment after fix" -ForegroundColor White
    Write-Host "     Verify: Check role assignments in Azure portal" -ForegroundColor White
    Write-Host ""
    
    # ===============================
    # DETAILED ERROR BREAKDOWN
    # ===============================
    Write-Host "DETAILED ERROR BREAKDOWN:" -ForegroundColor Cyan
    Write-Host ""
    
    $errorGroups = $uniqueErrors | Group-Object ErrorCode
    foreach ($group in $errorGroups) {
        Write-Host "  * $($group.Name): $($group.Count) occurrence(s)" -ForegroundColor White
        $group.Group | ForEach-Object {
            if ($_.BicepModule) {
                Write-Host "    Module: $($_.BicepModule)" -ForegroundColor Gray
            }
        }
        Write-Host ""
    }
    
    # Add specific actions section
    $recNumber++
    Write-Host ""
    Write-Host "=====================================================================================================" -ForegroundColor Cyan
    Write-Host "💡 ACTIONS:" -ForegroundColor Green
    Write-Host "=====================================================================================================" -ForegroundColor Cyan

    Write-Host "  $recNumber. SPECIFIC ACTIONS FOR YOUR ERRORS" -ForegroundColor Green
    Write-Host "     🔧 Action 1: Fix miRbac.bicep GUID generation" -ForegroundColor White
    Write-Host "     🔧 Action 2: Review role assignment dependencies" -ForegroundColor White
    Write-Host "     🔧 Action 3: Check for duplicate module calls" -ForegroundColor White
    Write-Host ""
    
} else {
    Write-Host "No errors found or unable to parse error information." -ForegroundColor Green
}

# Export to CSV for further analysis
$csvPath = $DebugFilePath.Replace(".md", "_parsed.csv")
$uniqueErrors | Export-Csv -Path $csvPath -NoTypeInformation
Write-Host "`nResults exported to: $csvPath" -ForegroundColor Cyan
