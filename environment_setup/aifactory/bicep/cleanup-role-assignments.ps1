# ================================================================
# Clean up problematic role assignments before redeployment
# Run this script if you get "RoleAssignmentUpdateNotPermitted" errors
# ================================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$SubscriptionId,
    
    [Parameter(Mandatory=$false)]
    [switch]$WhatIf
)

# Set subscription if provided
if ($SubscriptionId) {
    Write-Host "Setting subscription context to: $SubscriptionId" -ForegroundColor Cyan
    az account set --subscription $SubscriptionId
}

Write-Host "`nSearching for role assignments in resource group: $ResourceGroupName" -ForegroundColor Cyan

# Get all role assignments in the resource group
$roleAssignments = az role assignment list --resource-group $ResourceGroupName --query "[].{name:name, principalId:principalId, roleDefinitionName:roleDefinitionName, scope:scope}" -o json | ConvertFrom-Json

if ($roleAssignments.Count -eq 0) {
    Write-Host "No role assignments found in resource group." -ForegroundColor Yellow
    exit 0
}

Write-Host "`nFound $($roleAssignments.Count) role assignments:" -ForegroundColor Green

# Group by resource type
$storageAssignments = @()
$searchAssignments = @()
$cosmosAssignments = @()
$otherAssignments = @()

foreach ($assignment in $roleAssignments) {
    if ($assignment.scope -like "*/storageAccounts/*") {
        $storageAssignments += $assignment
    } elseif ($assignment.scope -like "*/searchServices/*") {
        $searchAssignments += $assignment
    } elseif ($assignment.scope -like "*/databaseAccounts/*") {
        $cosmosAssignments += $assignment
    } else {
        $otherAssignments += $assignment
    }
}

Write-Host "`n  Storage Account role assignments: $($storageAssignments.Count)"
Write-Host "  AI Search role assignments: $($searchAssignments.Count)"
Write-Host "  Cosmos DB role assignments: $($cosmosAssignments.Count)"
Write-Host "  Other role assignments: $($otherAssignments.Count)"

if ($WhatIf) {
    Write-Host "`n[WHATIF] Would delete the following role assignments:" -ForegroundColor Yellow
    
    Write-Host "`nStorage Account assignments:"
    $storageAssignments | ForEach-Object { Write-Host "  - $($_.roleDefinitionName) ($($_.name))" }
    
    Write-Host "`nAI Search assignments:"
    $searchAssignments | ForEach-Object { Write-Host "  - $($_.roleDefinitionName) ($($_.name))" }
    
    Write-Host "`nCosmos DB assignments:"
    $cosmosAssignments | ForEach-Object { Write-Host "  - $($_.roleDefinitionName) ($($_.name))" }
    
    Write-Host "`nOther assignments:"
    $otherAssignments | ForEach-Object { Write-Host "  - $($_.roleDefinitionName) ($($_.name))" }
    
    Write-Host "`nRun without -WhatIf to actually delete these assignments." -ForegroundColor Yellow
    exit 0
}

# Confirm deletion
Write-Host "`nWARNING: This will delete role assignments related to AI Foundry deployment." -ForegroundColor Red
$confirm = Read-Host "Type 'YES' to continue"

if ($confirm -ne 'YES') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

# Delete role assignments
$deletedCount = 0
$failedCount = 0

Write-Host "`nDeleting role assignments..." -ForegroundColor Cyan

foreach ($assignment in $roleAssignments) {
    try {
        Write-Host "  Deleting: $($assignment.roleDefinitionName) on $($assignment.scope)" -ForegroundColor Gray
        az role assignment delete --ids $assignment.name --output none 2>$null
        $deletedCount++
    } catch {
        Write-Host "  Failed to delete: $($assignment.name)" -ForegroundColor Red
        $failedCount++
    }
}

Write-Host "`nCleanup complete:" -ForegroundColor Green
Write-Host "  Deleted: $deletedCount"
Write-Host "  Failed: $failedCount"

if ($failedCount -eq 0) {
    Write-Host "`nYou can now redeploy your Bicep template." -ForegroundColor Green
} else {
    Write-Host "`nSome deletions failed. Check permissions and try again." -ForegroundColor Yellow
}
