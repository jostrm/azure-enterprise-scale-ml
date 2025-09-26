# Azure Monitor Private Link Scope (AMPLS) Deployment Script
# This script deploys AMPLS in a hub/spoke architecture for AI Factory

param(
    [Parameter(Mandatory=$true)]
    [string]$SubscriptionId,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$true)]
    [string]$Environment,
    
    [Parameter(Mandatory=$true)]
    [string]$Location,
    
    [Parameter(Mandatory=$true)]
    [string]$LocationSuffix,
    
    [Parameter(Mandatory=$true)]
    [string]$PrivDnsSubscription,
    
    [Parameter(Mandatory=$true)]
    [string]$PrivDnsResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$HubVnetName,
    
    [Parameter(Mandatory=$true)]
    [string]$HubVnetResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$MonitoringSubnetName = "snet-monitoring",
    
    [Parameter(Mandatory=$false)]
    [string]$CommonResourceSuffix = "-001",
    
    [Parameter(Mandatory=$false)]
    [string]$TemplateFile = ".\amplsIntegration.bicep",
    
    [Parameter(Mandatory=$false)]
    [string]$ParameterFile = ".\ampls.parameters.json",
    
    [Parameter(Mandatory=$false)]
    [array]$LogAnalyticsWorkspaceIds = @(),
    
    [Parameter(Mandatory=$false)]
    [array]$ApplicationInsightsIds = @(),
    
    [Parameter(Mandatory=$false)]
    [switch]$WhatIf
)

# Set error action preference
$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting AMPLS Deployment for AI Factory" -ForegroundColor Green
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Location: $Location ($LocationSuffix)" -ForegroundColor Yellow
Write-Host "Target Subscription: $SubscriptionId" -ForegroundColor Yellow
Write-Host "Target Resource Group: $ResourceGroupName" -ForegroundColor Yellow

try {
    # Connect to Azure if not already connected
    $context = Get-AzContext
    if (-not $context) {
        Write-Host "Connecting to Azure..." -ForegroundColor Yellow
        Connect-AzAccount
    }
    
    # Set the subscription context
    Write-Host "Setting subscription context to: $SubscriptionId" -ForegroundColor Yellow
    Set-AzContext -SubscriptionId $SubscriptionId
    
    # Verify resource group exists or create it
    $rg = Get-AzResourceGroup -Name $ResourceGroupName -ErrorAction SilentlyContinue
    if (-not $rg) {
        Write-Host "Creating resource group: $ResourceGroupName" -ForegroundColor Yellow
        New-AzResourceGroup -Name $ResourceGroupName -Location $Location
    }
    
    # Verify hub resource group and VNet exist
    Write-Host "Verifying hub infrastructure..." -ForegroundColor Yellow
    $hubRg = Get-AzResourceGroup -Name $HubVnetResourceGroup -SubscriptionId $PrivDnsSubscription -ErrorAction SilentlyContinue
    if (-not $hubRg) {
        throw "Hub resource group '$HubVnetResourceGroup' not found in subscription '$PrivDnsSubscription'"
    }
    
    $hubVnet = Get-AzVirtualNetwork -Name $HubVnetName -ResourceGroupName $HubVnetResourceGroup -SubscriptionId $PrivDnsSubscription -ErrorAction SilentlyContinue
    if (-not $hubVnet) {
        throw "Hub VNet '$HubVnetName' not found in resource group '$HubVnetResourceGroup'"
    }
    
    # Check if monitoring subnet exists
    $monitoringSubnet = $hubVnet.Subnets | Where-Object { $_.Name -eq $MonitoringSubnetName }
    if (-not $monitoringSubnet) {
        Write-Warning "Monitoring subnet '$MonitoringSubnetName' not found in hub VNet. Please create it before deploying AMPLS."
        Write-Host "Suggested subnet configuration:" -ForegroundColor Yellow
        Write-Host "  Name: $MonitoringSubnetName" -ForegroundColor White
        Write-Host "  Address Space: 10.0.10.0/24 (adjust based on your network)" -ForegroundColor White
        Write-Host "  Service Endpoints: Microsoft.Storage, Microsoft.KeyVault" -ForegroundColor White
        
        $continue = Read-Host "Continue anyway? (y/n)"
        if ($continue -ne 'y') {
            exit 1
        }
    }
    
    # Prepare deployment parameters
    $deploymentParams = @{
        env = $Environment
        location = $Location
        locationSuffix = $LocationSuffix
        commonResourceSuffix = $CommonResourceSuffix
        privDnsSubscription = $PrivDnsSubscription
        privDnsResourceGroup = $PrivDnsResourceGroup
        hubVnetName = $HubVnetName
        hubVnetResourceGroup = $HubVnetResourceGroup
        monitoringSubnetName = $MonitoringSubnetName
        existingLogAnalyticsWorkspaceIds = $LogAnalyticsWorkspaceIds
        existingApplicationInsightsIds = $ApplicationInsightsIds
        ingestionAccessMode = "PrivateOnly"
        queryAccessMode = "PrivateOnly"
        deployToHubResourceGroup = $true
        tags = @{
            Environment = $Environment
            Project = "AI Factory"
            Component = "AMPLS"
            DeployedBy = $env:USERNAME
            DeployedOn = (Get-Date).ToString("yyyy-MM-dd")
        }
    }
    
    # Deploy the template
    $deploymentName = "ampls-deployment-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    
    Write-Host "Starting deployment..." -ForegroundColor Green
    Write-Host "Deployment Name: $deploymentName" -ForegroundColor Yellow
    Write-Host "Template File: $TemplateFile" -ForegroundColor Yellow
    
    if ($WhatIf) {
        Write-Host "Running What-If analysis..." -ForegroundColor Yellow
        $result = New-AzResourceGroupDeployment `
            -ResourceGroupName $ResourceGroupName `
            -Name $deploymentName `
            -TemplateFile $TemplateFile `
            -TemplateParameterObject $deploymentParams `
            -WhatIf
        
        Write-Host "What-If analysis completed." -ForegroundColor Green
        return $result
    }
    else {
        $deployment = New-AzResourceGroupDeployment `
            -ResourceGroupName $ResourceGroupName `
            -Name $deploymentName `
            -TemplateFile $TemplateFile `
            -TemplateParameterObject $deploymentParams `
            -Verbose
        
        if ($deployment.ProvisioningState -eq "Succeeded") {
            Write-Host "✅ AMPLS deployment completed successfully!" -ForegroundColor Green
            
            # Display deployment outputs
            if ($deployment.Outputs) {
                Write-Host "`n📋 Deployment Outputs:" -ForegroundColor Cyan
                $deployment.Outputs | ConvertTo-Json -Depth 10 | Write-Host
            }
            
            # Post-deployment validation suggestions
            Write-Host "`n🔍 Post-Deployment Validation Steps:" -ForegroundColor Cyan
            Write-Host "1. Verify private DNS resolution:" -ForegroundColor White
            Write-Host "   nslookup ods.opinsights.azure.com" -ForegroundColor Gray
            Write-Host "2. Test private endpoint connectivity" -ForegroundColor White
            Write-Host "3. Configure Azure Monitor Agent to use private DCE" -ForegroundColor White
            Write-Host "4. Update network security groups if needed" -ForegroundColor White
            Write-Host "5. Test log ingestion and querying through private links" -ForegroundColor White
            
        }
        else {
            Write-Error "❌ Deployment failed with state: $($deployment.ProvisioningState)"
            exit 1
        }
        
        return $deployment
    }
}
catch {
    Write-Error "❌ Deployment failed: $($_.Exception.Message)"
    Write-Host "Full error details:" -ForegroundColor Red
    Write-Host $_.Exception -ForegroundColor Red
    exit 1
}
finally {
    Write-Host "`n🏁 AMPLS Deployment Script Completed" -ForegroundColor Green
}