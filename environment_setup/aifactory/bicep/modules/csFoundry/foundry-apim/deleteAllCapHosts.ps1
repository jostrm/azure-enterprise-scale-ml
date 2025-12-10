# Script to delete all capability hosts in accounts starting with "aif2"

# Prompt for required information
$subscriptionId = Read-Host "Enter Subscription ID"
$resourceGroup = Read-Host "Enter Resource Group name"

Write-Host "`nWARNING: This will DELETE all capability hosts found in accounts starting with 'aif2'!" -ForegroundColor Yellow
$confirm = Read-Host "Are you sure you want to continue? (yes/no)"

if ($confirm -ne "yes") {
    Write-Host "Operation cancelled."
    exit 0
}

# Get Azure access token
Write-Host "`nGetting Azure access token..."
$accessToken = az account get-access-token --query accessToken -o tsv

if ([string]::IsNullOrEmpty($accessToken)) {
    Write-Host "Error: Failed to get access token. Please make sure you're logged in with 'az login'"
    exit 1
}

# Construct the API URL to list all accounts
$apiUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.CognitiveServices/accounts?api-version=2024-10-01"

# Send GET request
$headers = @{
    Authorization = "Bearer $accessToken"
    "Content-Type" = "application/json"
}

try {
    Write-Host "Fetching accounts from resource group..."
    $response = Invoke-RestMethod -Uri $apiUrl -Headers $headers -Method Get
    
    Write-Host "Total accounts found: $($response.value.Count)"
    
    # Filter accounts starting with "aif2"
    $aif2Accounts = $response.value | Where-Object { $_.name -like "aif2*" }
    
    Write-Host "Accounts starting with 'aif2': $($aif2Accounts.Count)"
    
    if ($aif2Accounts.Count -eq 0) {
        Write-Host "No accounts starting with 'aif2' found in resource group."
        exit 0
    }
    
    $deletedCount = 0
    
    # Get projects and capability hosts for each account
    Write-Host "`nSearching for capability hosts to delete..."
    foreach ($account in $aif2Accounts) {
        $accountName = $account.name
        Write-Host "`nChecking account: $accountName"
        
        # First, list projects in this account
        $projectsUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.MachineLearningServices/workspaces?api-version=2024-10-01"
        
        try {
            $projectsResponse = Invoke-RestMethod -Uri $projectsUrl -Headers $headers -Method Get
            # Filter projects that belong to this account (hub)
            $accountProjects = $projectsResponse.value | Where-Object { 
                $_.properties.hubResourceId -like "*$accountName*" -or $_.name -like "*$accountName*"
            }
            
            if ($accountProjects.Count -eq 0) {
                Write-Host "  No projects found for this account"
            } else {
                Write-Host "  Found $($accountProjects.Count) project(s)"
                
                foreach ($project in $accountProjects) {
                    $projectName = $project.name
                    Write-Host "    Project: $projectName"
                    
                    # Now get capability hosts for this project
                    $caphostUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.MachineLearningServices/workspaces/$projectName/capabilityHosts?api-version=2024-10-01-preview"
                    
                    try {
                        $caphostResponse = Invoke-RestMethod -Uri $caphostUrl -Headers $headers -Method Get
                        if ($caphostResponse.value) {
                            foreach ($caphost in $caphostResponse.value) {
                                $caphostName = $caphost.name
                                Write-Host "      Found CapHost: $caphostName" -ForegroundColor Cyan
                                
                                # Delete the capability host
                                $deleteUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.MachineLearningServices/workspaces/$projectName/capabilityHosts/$caphostName`?api-version=2024-10-01-preview"
                                
                                try {
                                    Write-Host "      Deleting..." -ForegroundColor Yellow
                                    $deleteResponse = Invoke-WebRequest -Uri $deleteUrl -Headers $headers -Method Delete -UseBasicParsing
                                    
                                    # Check for async operation
                                    $asyncOpUrl = $deleteResponse.Headers['Azure-AsyncOperation']
                                    if ($asyncOpUrl) {
                                        Write-Host "      Monitoring deletion operation..." -ForegroundColor Yellow
                                        
                                        # Poll until complete
                                        $status = "InProgress"
                                        $maxAttempts = 60
                                        $attempt = 0
                                        
                                        while ($status -eq "InProgress" -and $attempt -lt $maxAttempts) {
                                            Start-Sleep -Seconds 5
                                            $attempt++
                                            
                                            try {
                                                $opResponse = Invoke-RestMethod -Uri $asyncOpUrl -Headers $headers -Method Get
                                                $status = $opResponse.status
                                                Write-Host "      Status: $status" -ForegroundColor Gray
                                            } catch {
                                                Write-Host "      Error checking status: $($_.Exception.Message)" -ForegroundColor Red
                                                break
                                            }
                                        }
                                        
                                        if ($status -eq "Succeeded") {
                                            Write-Host "      ✓ Successfully deleted: $caphostName" -ForegroundColor Green
                                            $deletedCount++
                                        } else {
                                            Write-Host "      ✗ Deletion failed or timed out: $caphostName (Status: $status)" -ForegroundColor Red
                                        }
                                    } else {
                                        Write-Host "      ✓ Successfully deleted: $caphostName" -ForegroundColor Green
                                        $deletedCount++
                                    }
                                } catch {
                                    Write-Host "      ✗ Error deleting: $($_.Exception.Message)" -ForegroundColor Red
                                }
                            }
                        }
                    } catch {
                        # Skip if no capability hosts
                    }
                }
            }
        } catch {
            Write-Host "  Error fetching projects: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "Summary: Deleted $deletedCount capability host(s)" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
