# ============================================================================
# Restart Kong ACI container group (after config update)
# Usage: ./restart-kong.ps1 -ResourceGroupName <rg> -SubscriptionId <sub>
# ============================================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory=$false)]
    [string]$ContainerGroupName = ""
)

# Set subscription context
az account set --subscription $SubscriptionId

# Find Kong container group if name not provided
if (-not $ContainerGroupName) {
    $ContainerGroupName = az container list `
        --resource-group $ResourceGroupName `
        --query "[?contains(name,'kong')].name" -o tsv
}

if (-not $ContainerGroupName) {
    Write-Error "No Kong container group found in resource group: $ResourceGroupName"
    exit 1
}

Write-Host "Restarting Kong container group: $ContainerGroupName"
az container restart `
    --resource-group $ResourceGroupName `
    --name $ContainerGroupName

if ($LASTEXITCODE -eq 0) {
    Write-Host "Kong container group restarted successfully"
    
    # Wait for container to be running
    Write-Host "Waiting for container to be ready..."
    az container show `
        --resource-group $ResourceGroupName `
        --name $ContainerGroupName `
        --query "{Status:instanceView.state, IP:ipAddress.ip, Ports:ipAddress.ports[].port}" -o table
} else {
    Write-Error "Failed to restart Kong container group"
    exit 1
}
