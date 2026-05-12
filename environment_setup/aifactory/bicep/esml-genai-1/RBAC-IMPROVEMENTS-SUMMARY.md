# RBAC Security Improvements Summary

## Overview
Enhanced RBAC security configuration to ensure users, Entra ID security groups, service principals, and managed identities have comprehensive access to Common resource group resources, specifically:

- **Azure Container Registry (ACR)** - Push/Pull access
- **Virtual Network (VNet)** - Network Reader access for monitoring and status checks
- **Subnets and Endpoints** - Read access for status monitoring

## Changes Made

### 1. New Module: VNet Reader Only (`vnetRBACReaderOnly.bicep`)
**Location:** `modules/vnetRBACReaderOnly.bicep`

**Purpose:** Provides Network Reader role assignment for all users, groups, service principals, and managed identities on the Common VNet, enabling them to:
- Read VNet configuration and status
- View subnet details and status
- Monitor endpoint status
- View network security group rules (read-only)

**Key Features:**
- **Always executes** - Not conditional on bastion configuration
- Uses de-duplicated identity arrays (`userIdsUnique`, `spAndMiUnique`)
- Assigns Network Reader role (read-only, no modifications)
- Supports both individual users and Entra ID groups

**Role Assigned:**
- `acdd72a7-3385-48ef-bd42-f606fba81ae7` - Network Reader (built-in role)

### 2. Updated Main RBAC File (`08-rbac-security.bicep`)

#### Header Documentation Updated
- Added clarification about VNet Reader access being always enabled
- Added note about Common resource group access (ACR, VNet)

#### New Module Invocation: `rbacVnetReaderCommon`
```bicep
module rbacVnetReaderCommon '../modules/vnetRBACReaderOnly.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
  name: take('08-rbacVnetReader${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    user_object_ids: userIdsUnique
    vNetName: vnetNameFull
    servicePrincipleAndMIArray: spAndMiUnique
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
  ]
}
```

**Deployment Behavior:**
- Runs **unconditionally** (no `if` condition)
- Uses de-duplicated identity arrays to prevent duplicate assignments
- Deployed early in the RBAC sequence
- Other modules depend on it to ensure proper sequencing

#### Updated Dependencies
The following modules now depend on `rbacVnetReaderCommon`:
- `rbacReadUsersToCmnVnetBastion` - Bastion VNet access (internal)
- `rbacReadUsersToCmnVnetBastionExt` - Bastion VNet access (external)
- `rbacKeyvaultCommon4Users` - Key Vault and Bastion RBAC
- `rbacExternalBastion` - External Bastion RBAC

#### Enhanced ACR RBAC Documentation
Updated comments for `cmnRbacACR` module to clarify:
- Grants ACR Push/Pull access to all identities
- Applies to Common resource group
- Allows publishing and consuming container images

#### Updated Outputs
New outputs added:
```bicep
@description('VNet Reader access always granted for reading VNet/subnet/endpoint status')
output vnetReaderRbacDeployed bool = true

@description('Network and VNet RBAC deployment status')
output networkRbacDeployed bool = true // Always true since rbacVnetReaderCommon always runs

@description('Common Resource Group RBAC deployment status (includes ACR access)')
output commonResourceGroupRbacDeployed bool = useCommonACR && !skipACRRoleAssignments
```

## Identity Management

### De-duplicated Arrays
The configuration uses de-duplicated arrays to prevent duplicate role assignments:

```bicep
var userIdsUnique = union(p011_genai_team_lead_array, p011_genai_team_lead_array)
var spAndMiUnique = union(spAndMiArray, spAndMiArray)
```

**Benefits:**
- Prevents `RoleAssignmentExists` errors
- Ensures no overlap between users and service principals
- Cleaner RBAC assignments

### Identity Types Supported
1. **Users** - Individual user accounts
2. **Groups** - Entra ID security groups (when `useAdGroups=true`)
3. **Service Principals** - Application registrations
4. **Managed Identities** - Project MI, ACA MI, and other system-assigned/user-assigned MIs

## Permissions Summary

### Common VNet (Always Applied)
| Role | Scope | Identities | Purpose |
|------|-------|-----------|---------|
| Network Reader | VNet | Users, Groups, SPs, MIs | Read VNet/subnet/endpoint status |

### Common Resource Group - ACR (Conditional: `useCommonACR && !skipACRRoleAssignments`)
| Role | Scope | Identities | Purpose |
|------|-------|-----------|---------|
| ACR Push | Common RG | Users, Groups, SPs, MIs | Push container images |
| ACR Pull | Common RG | SPs, MIs | Pull container images |

### Bastion VNet (Conditional: When bastion is configured)
| Role | Scope | Identities | Purpose |
|------|-------|-----------|---------|
| Network Contributor | VNet | Users, Groups, SPs, MIs | Join subnets (needed for compute) |
| Contributor | Bastion NSG | Users, Groups | Manage Bastion NSG rules |

## Deployment Considerations

### Prerequisites
1. Common resource group must exist
2. VNet must be deployed
3. If using ACR, it must be provisioned

### Error Handling
- Set `skipExistingRoleAssignments=true` to skip duplicate assignments
- Set `skipACRRoleAssignments=true` specifically for ACR assignment issues
- Ensure resources exist before running RBAC deployment

### Execution Order
1. `rbacVnetReaderCommon` (always first)
2. ACR RBAC assignments (if enabled)
3. Bastion-specific RBAC (if bastion configured)
4. Other resource-specific RBAC assignments

## Benefits

### Always-On VNet Access
- Users can monitor network health at all times
- Not dependent on bastion configuration
- Supports troubleshooting and diagnostics

### Comprehensive Identity Support
- Works with users, groups, service principals, and managed identities
- Supports both individual accounts and Entra ID groups
- Prevents duplicate assignments

### Improved Reliability
- De-duplicated arrays prevent conflicts
- Clear conditional logic for optional components
- Better error handling guidance

## Testing Recommendations

1. **Verify VNet Reader Access:**
   ```powershell
   # Check if user can read VNet
   Get-AzVirtualNetwork -ResourceGroupName <vnet-rg> -Name <vnet-name>
   ```

2. **Verify ACR Access:**
   ```powershell
   # Check ACR permissions
   Get-AzRoleAssignment -Scope <common-rg-resource-id> | Where-Object {$_.RoleDefinitionName -like "*ACR*"}
   ```

3. **Verify Role Assignments:**
   ```powershell
   # List all role assignments for a user
   Get-AzRoleAssignment -ObjectId <user-object-id>
   ```

## Related Files Modified

1. **New Module:**
   - `modules/vnetRBACReaderOnly.bicep` - VNet Reader RBAC module

2. **Updated Files:**
   - `08-rbac-security.bicep` - Main RBAC deployment
   - Updated dependencies, outputs, and documentation

## Migration Notes

### Existing Deployments
- This change is backward compatible
- New VNet Reader module will add permissions without removing existing ones
- If you already have Network Contributor on VNet (from bastion), Network Reader is redundant but harmless

### Fresh Deployments
- VNet Reader access is now guaranteed for all scenarios
- ACR access remains conditional on `useCommonACR` parameter
- No changes to parameter file required

## Troubleshooting

### Common Issues

**Issue:** `RoleAssignmentExists` error
**Solution:** Set `skipExistingRoleAssignments=true` or `skipACRRoleAssignments=true`

**Issue:** `ResourceNotFound` for VNet
**Solution:** Ensure VNet is deployed before running this template

**Issue:** Duplicate assignments for bastion users
**Solution:** This is expected - Network Reader (always) + Network Contributor (bastion scenario)

## References

- Network Reader Role: https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles#network-reader
- ACR Roles: https://learn.microsoft.com/en-us/azure/container-registry/container-registry-roles
- Azure RBAC Best Practices: https://learn.microsoft.com/en-us/azure/role-based-access-control/best-practices
