# Get Existing Application Insights from AMPLS
# This script queries an existing AMPLS and returns the Application Insights resource IDs
# to be used as parameters when adding new Application Insights resources

param(
    [Parameter(Mandatory=$true)]
    [string]$AmplsName,
    
    [Parameter(Mandatory=$true)]
    [string]$AmplsResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$AmplsSubscription = "",
    
    [Parameter(Mandatory=$false)]
    [switch]$OutputAsJson
)

# Set error action preference
$ErrorActionPreference = "Stop"

try {
    # Set subscription context if provided
    if (-not [string]::IsNullOrEmpty($AmplsSubscription)) {
        Set-AzContext -SubscriptionId $AmplsSubscription | Out-Null
    }
    
    # Get the AMPLS resource
    $ampls = Get-AzResource -ResourceGroupName $AmplsResourceGroup -Name $AmplsName -ResourceType "microsoft.insights/privateLinkScopes"
    
    if (-not $ampls) {
        Write-Warning "AMPLS '$AmplsName' not found in resource group '$AmplsResourceGroup'"
        if ($OutputAsJson) {
            return @{
                existingApplicationInsightsIds = @()
                existingLogAnalyticsWorkspaceIds = @()
                existingDataCollectionEndpointIds = @()
            } | ConvertTo-Json
        }
        else {
            return @{
                ApplicationInsights = @()
                LogAnalyticsWorkspaces = @()
                DataCollectionEndpoints = @()
            }
        }
    }
    
    # Get scoped resources from AMPLS
    $scopedResources = Get-AzResource -ResourceGroupName $AmplsResourceGroup -ResourceType "microsoft.insights/privateLinkScopes/scopedResources" -ResourceName "$AmplsName/*"
    
    $applicationInsightsIds = @()
    $logAnalyticsWorkspaceIds = @()
    $dataCollectionEndpointIds = @()
    
    foreach ($resource in $scopedResources) {
        $linkedResourceId = $resource.Properties.linkedResourceId
        
        if ($linkedResourceId -like "*/Microsoft.Insights/components/*") {
            $applicationInsightsIds += $linkedResourceId
        }
        elseif ($linkedResourceId -like "*/Microsoft.OperationalInsights/workspaces/*") {
            $logAnalyticsWorkspaceIds += $linkedResourceId
        }
        elseif ($linkedResourceId -like "*/Microsoft.Insights/dataCollectionEndpoints/*") {
            $dataCollectionEndpointIds += $linkedResourceId
        }
    }
    
    $result = @{
        existingApplicationInsightsIds = $applicationInsightsIds
        existingLogAnalyticsWorkspaceIds = $logAnalyticsWorkspaceIds
        existingDataCollectionEndpointIds = $dataCollectionEndpointIds
    }
    
    if ($OutputAsJson) {
        return $result | ConvertTo-Json -Depth 10
    }
    else {
        Write-Host "Found $($applicationInsightsIds.Count) Application Insights resources" -ForegroundColor Green
        Write-Host "Found $($logAnalyticsWorkspaceIds.Count) Log Analytics Workspaces" -ForegroundColor Green
        Write-Host "Found $($dataCollectionEndpointIds.Count) Data Collection Endpoints" -ForegroundColor Green
        
        return $result
    }
}
catch {
    Write-Error "Failed to query AMPLS: $($_.Exception.Message)"
    throw
}