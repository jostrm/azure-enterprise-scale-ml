# Script to list all capability hosts in accounts starting with "aif2"

# Prompt for required information
$subscriptionId = Read-Host "Enter Subscription ID"
$resourceGroup = Read-Host "Enter Resource Group name"

# Get Azure access token
Write-Host "Getting Azure access token..."
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
    
    # Show all account names
    Write-Host "All accounts:"
    $response.value | ForEach-Object { Write-Host "  - $($_.name)" }
    
    # Filter accounts starting with "aif2"
    $aif2Accounts = $response.value | Where-Object { $_.name -like "aif2*" }
    
    Write-Host "`nAccounts starting with 'aif2': $($aif2Accounts.Count)"
    
    if ($aif2Accounts.Count -eq 0) {
        Write-Host "No accounts starting with 'aif2' found in resource group."
        exit 0
    }
    
    # Get projects and capability hosts for each account
    Write-Host "`nFetching projects and capability hosts..."
    foreach ($account in $aif2Accounts) {
        $accountName = $account.name
        Write-Host "Checking account: $accountName"
        
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
                            $caphostResponse.value | ForEach-Object { 
                                Write-Host "      CapHost: $($_.name)"
                            }
                        }
                    } catch {
                        # Skip if no capability hosts
                    }
                }
            }
        } catch {
            Write-Host "  Error fetching projects: $($_.Exception.Message)"
        }
    }
} catch {
    Write-Host "Error: $($_.Exception.Message)"
    Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)"
    exit 1
}
