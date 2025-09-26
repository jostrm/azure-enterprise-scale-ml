# Azure Monitor Private Link Scope (AMPLS) Modules

This folder contains Bicep modules for deploying Azure Monitor Private Link Scope (AMPLS) in a hub/spoke network architecture, designed to integrate with the AI Factory infrastructure.

## Overview

Azure Monitor Private Link Scope (AMPLS) enables secure monitoring by routing Azure Monitor traffic through private endpoints, eliminating the need for public internet access.

## Architecture

```
Hub Subscription (privDnsSubscription_param)
└── Hub Resource Group (privDnsResourceGroup_param)
    ├── Private DNS Zones
    │   ├── privatelink.monitor.azure.com
    │   ├── privatelink.oms.opinsights.azure.com
    │   ├── privatelink.ods.opinsights.azure.com
    │   └── privatelink.agentsvc.azure-automation.net
    ├── Azure Monitor Private Link Scope (AMPLS)
    ├── Data Collection Endpoint (DCE)
    └── Private Endpoints
```

## Modules

### Core Modules

1. **`ampls.bicep`** - Creates the Azure Monitor Private Link Scope and connects monitoring resources
2. **`amplsPrivateEndpoint.bicep`** - Creates private endpoints for AMPLS with DNS integration
3. **`dataCollectionEndpoint.bicep`** - Creates Data Collection Endpoints for Azure Monitor Agent

### Orchestration Modules

4. **`amplsHubSimple.bicep`** - Simplified hub deployment that combines all components
5. **`amplsIntegration.bicep`** - Integration module for existing AI Factory deployments

## Usage

### Option 1: Integration with Existing AI Factory Foundation

Use `amplsIntegration.bicep` to add AMPLS to an existing AI Factory deployment:

```bicep
module amplsIntegration '../modules/monitoring/amplsIntegration.bicep' = {
  name: 'ampls-integration'
  params: {
    env: env
    location: location
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    tags: tags
    privDnsSubscription: privDnsSubscription_param
    privDnsResourceGroup: privDnsResourceGroup_param
    hubVnetName: vnetNameFull
    hubVnetResourceGroup: vnetResourceGroupName
    existingLogAnalyticsWorkspaceIds: [
      logAnalyticsWorkspace.outputs.logAnalyticsWkspId
    ]
    existingApplicationInsightsIds: [
      applicationInsights.outputs.id
    ]
  }
}
```

### Option 2: Standalone Hub Deployment

Use `amplsHubSimple.bicep` for a standalone AMPLS deployment:

```bicep
module amplsHub '../modules/monitoring/amplsHubSimple.bicep' = {
  name: 'ampls-hub-deployment'
  scope: resourceGroup(privDnsSubscription, privDnsResourceGroup)
  params: {
    env: 'dev'
    location: 'East US 2'
    locationSuffix: 'eus2'
    commonResourceSuffix: '-001'
    hubVnetName: 'vnet-hub-eus2-dev-001'
    hubVnetResourceGroup: 'rg-hub-network-eus2-dev-001'
    logAnalyticsWorkspaces: [...]
    applicationInsightsComponents: [...]
    privateDnsZoneResourceIds: {...}
  }
}
```

### Option 3: Individual Components

Deploy individual components using the core modules for maximum flexibility.

## Parameters

### Required Parameters

- `env`: Environment (dev, test, prod)
- `location`: Azure region
- `locationSuffix`: Location abbreviation (e.g., 'eus2', 'weu')
- `privDnsSubscription`: Subscription containing private DNS zones
- `privDnsResourceGroup`: Resource group containing private DNS zones
- `hubVnetName`: Hub virtual network name
- `hubVnetResourceGroup`: Hub virtual network resource group

### Optional Parameters

- `ingestionAccessMode`: Controls data ingestion access ('Open' or 'PrivateOnly')
- `queryAccessMode`: Controls data query access ('Open' or 'PrivateOnly')
- `monitoringSubnetName`: Subnet name for private endpoints (default: 'snet-monitoring')

## Prerequisites

1. **Hub/Spoke Network**: Existing hub virtual network with appropriate subnets
2. **Private DNS Zones**: The following private DNS zones must exist or be created:
   - `privatelink.monitor.azure.com`
   - `privatelink.oms.opinsights.azure.com`
   - `privatelink.ods.opinsights.azure.com`
   - `privatelink.agentsvc.azure-automation.net`
3. **Monitoring Subnet**: Dedicated subnet in hub VNet for monitoring private endpoints
4. **RBAC Permissions**: Appropriate permissions in hub subscription/resource group

## Security Considerations

### Network Isolation

- Set both `ingestionAccessMode` and `queryAccessMode` to `'PrivateOnly'` for maximum security
- Ensure NSGs allow traffic to Azure Monitor service tags:
  - `AzureMonitor`
  - `AzureResourceManager`
  - `Storage` (for diagnostic data)

### Access Control

- Use managed identities for Azure Monitor Agent authentication
- Implement proper RBAC for AMPLS and connected resources
- Consider Data Collection Rules (DCR) for fine-grained access control

### DNS Configuration

- Private DNS zones automatically resolve Azure Monitor endpoints to private IPs
- Ensure DNS forwarding is configured for hybrid scenarios
- Test DNS resolution from spoke networks

## Best Practices

1. **Single AMPLS per DNS Zone**: Use one AMPLS per private DNS zone to avoid conflicts
2. **Hub Deployment**: Deploy AMPLS in the hub subscription/resource group
3. **Monitoring Subnet**: Use dedicated subnet for monitoring private endpoints
4. **Progressive Rollout**: Start with `'Open'` access modes, then transition to `'PrivateOnly'`
5. **Resource Organization**: Group all monitoring resources in the same resource group
6. **Tagging Strategy**: Apply consistent tags for cost management and governance

## Troubleshooting

### Common Issues

1. **DNS Resolution**: Verify private DNS zones are linked to all relevant VNets
2. **Network Connectivity**: Check NSG rules and route tables
3. **Agent Issues**: Ensure Azure Monitor Agent uses private DCE endpoints
4. **Certificate Issues**: Disable HTTPS inspection for Azure Monitor traffic

### Validation Commands

```powershell
# Test DNS resolution
nslookup ods.opinsights.azure.com

# Test private endpoint connectivity
Test-NetConnection -ComputerName <private-endpoint-ip> -Port 443

# Check AMPLS configuration
az monitor private-link-scope show --name <ampls-name> --resource-group <rg-name>
```

## Example Deployment

See `ampls.parameters.json` for a complete parameter file example.

## References

- [Azure Monitor Private Link documentation](https://docs.microsoft.com/en-us/azure/azure-monitor/logs/private-link-security)
- [AI Factory Architecture Guide](../../README.md)
- [Azure Monitor Agent Private Link](https://docs.microsoft.com/en-us/azure/azure-monitor/agents/azure-monitor-agent-private-link)