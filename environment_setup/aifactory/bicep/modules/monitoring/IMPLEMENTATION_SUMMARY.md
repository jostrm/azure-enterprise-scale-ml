# Azure Monitor Private Link Scope (AMPLS) - Implementation Summary

## ✅ Created BICEP Modules

The following BICEP modules have been created in `environment_setup\aifactory\bicep\modules\monitoring\`:

### Core Modules
1. **`ampls.bicep`** - Creates Azure Monitor Private Link Scope and connects monitoring resources
2. **`amplsPrivateEndpoint.bicep`** - Creates private endpoints with DNS integration
3. **`dataCollectionEndpoint.bicep`** - Creates Data Collection Endpoints for Azure Monitor Agent

### Orchestration Modules
4. **`amplsHubSimple.bicep`** - Complete hub deployment combining all components
5. **`amplsIntegration.bicep`** - Integration module for existing AI Factory deployments

### Supporting Files
6. **`ampls.parameters.json`** - Example parameter file
7. **`Deploy-AMPLS.ps1`** - PowerShell deployment script
8. **`README.md`** - Comprehensive documentation
9. **`foundationIntegrationExample.bicep`** - Example integration with foundation

## 🏗️ Architecture Implemented

```
Hub Subscription (privDnsSubscription_param)
└── Hub Resource Group (privDnsResourceGroup_param)
    ├── Private DNS Zones ✅
    │   ├── privatelink.monitor.azure.com
    │   ├── privatelink.oms.opinsights.azure.com
    │   ├── privatelink.ods.opinsights.azure.com
    │   └── privatelink.agentsvc.azure-automation.net
    ├── Azure Monitor Private Link Scope (AMPLS) ✅
    ├── Data Collection Endpoint (DCE) ✅
    └── Private Endpoints ✅
```

## 🎯 Key Features Implemented

### Security & Isolation ✅
- **PrivateOnly** access modes for both ingestion and query
- Network isolation through private endpoints
- Private DNS integration for seamless resolution
- Support for Data Collection Endpoints (DCE)

### Hub/Spoke Design ✅
- Centralized AMPLS deployment in hub resource group
- Private DNS zones in hub subscription
- Cross-subscription support for spoke resources
- Proper RBAC and resource organization

### AI Factory Integration ✅
- Uses existing `privDnsSubscription_param` and `privDnsResourceGroup_param`
- Integrates with foundation deployment pattern
- Follows existing naming conventions
- Compatible with current networking architecture

### Flexibility ✅
- Modular design allowing individual or combined deployments
- Conditional deployment support
- Configurable access modes (Open vs PrivateOnly)
- Support for existing and new monitoring resources

## 📋 Deployment Options

### Option 1: Integration with Foundation (Recommended)
Add to your existing foundation deployment:
```bicep
module amplsIntegration '../modules/monitoring/amplsIntegration.bicep' = {
  // ... parameters from foundation variables
}
```

### Option 2: Standalone Deployment
Use the PowerShell script:
```powershell
.\Deploy-AMPLS.ps1 -SubscriptionId "xxx" -ResourceGroupName "rg-hub" -Environment "dev" ...
```

### Option 3: Individual Components
Deploy modules separately for maximum control

## 🔒 Security Implementation

### Access Modes
- **Ingestion**: `PrivateOnly` - Only private endpoints can ingest data
- **Query**: `PrivateOnly` - Only private endpoints can query data

### Network Security
- Private endpoints in dedicated monitoring subnet
- DNS resolution through private DNS zones
- Support for NSG rules and service tags

### RBAC
- Managed identities for service authentication
- Proper permissions for AMPLS and connected resources
- Data Collection Rules (DCR) support

## 🌐 DNS Configuration

The modules leverage existing private DNS zones from the AI Factory foundation:
- `privatelink.monitor.azure.com` - General Azure Monitor traffic
- `privatelink.oms.opinsights.azure.com` - Log Analytics ingestion
- `privatelink.ods.opinsights.azure.com` - Log Analytics query
- `privatelink.agentsvc.azure-automation.net` - Azure Monitor Agent

## ✅ Best Practices Implemented

1. **Single AMPLS per DNS Zone** - Avoids DNS conflicts
2. **Hub Deployment** - Centralized in hub subscription/resource group
3. **Dedicated Subnet** - Monitoring subnet for private endpoints
4. **Progressive Rollout** - Support for Open → PrivateOnly transition
5. **Resource Organization** - Grouped monitoring resources
6. **Consistent Tagging** - Cost management and governance
7. **Error Handling** - Proper validation and error messages

## 🚀 Next Steps

1. **Review Parameters** - Update `ampls.parameters.json` with your values
2. **Create Monitoring Subnet** - Ensure hub VNet has monitoring subnet
3. **Deploy AMPLS** - Use integration module or PowerShell script
4. **Configure Agents** - Update Azure Monitor Agent to use private DCE
5. **Test Connectivity** - Validate private endpoint resolution and connectivity
6. **Update NSGs** - Ensure proper service tag configuration

## 📚 Documentation

Comprehensive documentation is provided in `README.md` including:
- Architecture diagrams
- Parameter explanations
- Troubleshooting guide
- Validation commands
- Security considerations

## 🎉 Benefits Achieved

- **Enhanced Security** - All monitoring traffic through private links
- **Network Isolation** - No internet traffic for Azure Monitor
- **Centralized Management** - Hub-based AMPLS for all spokes
- **Scalability** - Easy to add new monitoring resources
- **Compliance** - Meets enterprise security requirements
- **Cost Optimization** - Reduced egress costs through private links

The AMPLS implementation is now ready for deployment in your AI Factory hub/spoke architecture! 🚀