# AI Foundry Network Configuration Guide

## Overview

This guide explains how to properly configure networking for AI Foundry deployments to avoid common issues:

1. ❌ **Not injected into the expected subnet**
2. ❌ **Using a different DNS path**
3. ❌ **Missing VNet integration**
4. ❌ **Using "Basic setup" instead of "Standard setup with private networking"**
5. ❌ **Capability host provisioned before DNS/private endpoint existed**

## Network Setup Types

### Basic Setup (No Agent Network Injection)

**When to use:**
- You want agents to run with public endpoints
- You don't need agents injected into your VNet
- You're using public access with IP whitelisting

**Configuration:**
```bicep
param disableAgentNetworkInjection = true
param aca2SubnetId = ''  // Can be empty
param enableCaphost = true  // Optional
```

**Behavior:**
- ✅ No subnet delegation required
- ✅ Account-level capability host created explicitly via Bicep
- ✅ Project-level capability host created in same deployment
- ✅ Faster deployment (no 15-60 min wait for auto-provisioning)
- ⚠️ Agents use public endpoints (less secure)

### Standard Setup with Private Networking (Agent Network Injection)

**When to use:**
- You want agents fully integrated into your private VNet
- You need private connectivity for agent workloads
- You're deploying with enterprise security requirements

**Configuration:**
```bicep
param disableAgentNetworkInjection = false
param aca2SubnetId = '/subscriptions/.../subnets/aca-agents-subnet'  // REQUIRED
param enableCaphost = true
param enableCosmosDB = true  // REQUIRED for agent network injection
```

**Behavior:**
- ✅ Agents injected into your specified subnet
- ✅ Full private networking for agent workloads
- ✅ Platform auto-provisions account-level capability host
- ⚠️ Requires subnet delegation to `Microsoft.App/environments`
- ⚠️ **Account-level caphost takes 15-60 minutes to provision**
- ⚠️ **Requires TWO deployments:**
  - **First deployment:** Creates account with `networkInjections`, waits for account caphost
  - **Second deployment:** Creates project-level capability host

## Critical Configuration Rules

### Rule 1: Agent Subnet Must Be Provided

**Problem:**
```bicep
param disableAgentNetworkInjection = false
param aca2SubnetId = ''  // ❌ ERROR: Missing subnet!
```

**Solution:**
```bicep
param disableAgentNetworkInjection = false
param aca2SubnetId = '/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/aca-agents-subnet'
```

**Validation:**
The template now includes validation that will output a warning:
```
ERROR: Standard setup with private networking requires aca2SubnetId when disableAgentNetworkInjection=false.
```

### Rule 2: Subnet Delegation Required for Standard Setup

**Problem:**
Subnet not delegated to `Microsoft.App/environments`

**Solution:**
The template automatically configures subnet delegation when:
```bicep
var requiresAcaDelegation = enableAIFoundry && !aiFoundryV2Exists && !disableAgentNetworkInjection
```

### Rule 3: Cosmos DB Required for Agent Network Injection

**Problem:**
```bicep
param disableAgentNetworkInjection = false
param enableCosmosDB = false  // ❌ ERROR: Cosmos required!
```

**Solution:**
```bicep
param disableAgentNetworkInjection = false
param enableCosmosDB = true  // ✅ Required for thread storage
```

### Rule 4: Two-Phase Deployment for Standard Setup

**Phase 1 (foundryV22AccountOnly=true):**
- Creates AI Foundry account with `networkInjections`
- Platform auto-provisions account-level capability host (15-60 min)
- **Wait:** Pipeline task polls until account caphost status = Succeeded

**Phase 2 (foundryV22AccountOnly=false):**
- Creates project with connections
- Creates project-level capability host
- Configures RBAC, private endpoints, DNS

**Code Logic:**
```bicep
// Account caphost: only create explicitly in Basic setup
module addAccountCapabilityHost '../modules/csFoundry/aiFoundry2025AccountCaphost.bicep' = 
  if(enableCaphost && disableAgentNetworkInjection && ...) { ... }

// Project caphost: skip in first deployment when using Standard setup
module addProjectCapabilityHost '../modules/csFoundry/aiFoundry2025caphost.bicep' = 
  if(... && (disableAgentNetworkInjection || aiFoundryV2Exists)) { ... }
```

### Rule 5: DNS and Private Endpoints Before Capability Host

**Problem:**
Capability host created before private DNS zones and endpoints are ready.

**Solution:**
The template enforces dependency order:
```bicep
module addProjectCapabilityHost '../modules/csFoundry/aiFoundry2025caphost.bicep' = ... {
  dependsOn: [
    rbacPreCaphost                      // RBAC configured first
    projectV21                          // Project and connections exist
    rbacAISearchForAIFv21              // AI Search RBAC in place
    rbacAIStorageAccountsForAIFv21     // Storage RBAC in place
    ...(disableAgentNetworkInjection ? [addAccountCapabilityHost] : [])
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
    // Private endpoints deployed separately with explicit dependencies
  ]
}
```

## Troubleshooting

### Check Network Configuration Outputs

After deployment, check these outputs:

```bash
az deployment sub show \
  --name "your-deployment" \
  --query "properties.outputs.networkConfigurationValidation.value"
```

**Expected outputs:**
```json
{
  "agentNetworkInjectionEnabled": true,
  "agentSubnetProvided": true,
  "agentSubnetId": "/subscriptions/.../subnets/aca-agents-subnet",
  "disableAgentNetworkInjection": false,
  "setupType": "Standard setup with private networking",
  "subnetDelegationConfigured": true,
  "validationMessage": "OK: Agent network configuration is valid.",
  "caphostWarning": "OK: Network setup is appropriate for capability host configuration."
}
```

### Common Issues and Fixes

#### Issue 1: "The customerSubnet property must match the subnet recorded on the Foundry account"

**Cause:** Account has `networkInjections` with subnet A, but capability host tries to use subnet B.

**Fix:**
Ensure the same subnet is used:
```bicep
// In account creation
networkInjections: [{
  scenario: 'agent'
  subnetArmId: aca2SubnetId  // Must match capability host subnet
}]

// In capability host
customerSubnet: aca2SubnetId  // Must match account networkInjections
```

#### Issue 2: "Account capability host timeout"

**Cause:** Deploying account caphost explicitly when platform is auto-provisioning it.

**Fix:**
Only deploy explicitly in Basic setup:
```bicep
module addAccountCapabilityHost '...' = 
  if(enableCaphost && disableAgentNetworkInjection && ...) { ... }
```

For Standard setup, let platform auto-provision and use pipeline wait task.

#### Issue 3: "Project capability host fails - account caphost not found"

**Cause:** Trying to create project caphost before account caphost exists.

**Fix:**
Use two-phase deployment:
- Phase 1: `foundryV22AccountOnly=true`, wait for account caphost
- Phase 2: `foundryV22AccountOnly=false`, create project caphost

#### Issue 4: "DNS resolution fails for agents"

**Cause:** Private DNS zones not properly configured or linked.

**Fix:**
Ensure DNS zones are deployed first:
```bicep
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = { ... }

var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

var aiFoundryNetworkingConfig = union({
  aiServicesPrivateDnsZoneResourceId: privateLinksDnsZones.servicesai.id
  cognitiveServicesPrivateDnsZoneResourceId: privateLinksDnsZones.cognitiveservices.id
  openAiPrivateDnsZoneResourceId: privateLinksDnsZones.openai.id
}, ... )
```

## Recommended Deployment Flow

### For Basic Setup (Faster, Less Secure)

```bash
# Single deployment
az deployment sub create \
  --location westeurope \
  --template-file 09-ai-foundry-2025-v4.bicep \
  --parameters @parameters.json \
  --parameters \
    disableAgentNetworkInjection=true \
    enableCaphost=true \
    foundryV22AccountOnly=false
```

### For Standard Setup (Slower, More Secure)

```bash
# Phase 1: Account creation
az deployment sub create \
  --location westeurope \
  --template-file 09-ai-foundry-2025-v4.bicep \
  --parameters @parameters.json \
  --parameters \
    disableAgentNetworkInjection=false \
    aca2SubnetId="/subscriptions/.../subnets/aca-agents-subnet" \
    enableCosmosDB=true \
    enableCaphost=true \
    foundryV22AccountOnly=true

# Wait for account capability host (15-60 minutes)
# Use pipeline wait task or manual check

# Phase 2: Project and capability host
az deployment sub create \
  --location westeurope \
  --template-file 09-ai-foundry-2025-v4.bicep \
  --parameters @parameters.json \
  --parameters \
    disableAgentNetworkInjection=false \
    aca2SubnetId="/subscriptions/.../subnets/aca-agents-subnet" \
    enableCosmosDB=true \
    enableCaphost=true \
    foundryV22AccountOnly=false \
    aiFoundryV2Exists=true
```

## Validation Checklist

Before deploying, verify:

- [ ] **Subnet configured**: `aca2SubnetId` provided if `disableAgentNetworkInjection=false`
- [ ] **Cosmos DB enabled**: `enableCosmosDB=true` if `disableAgentNetworkInjection=false`
- [ ] **Subnet delegation**: Subnet delegated to `Microsoft.App/environments` for Standard setup
- [ ] **DNS zones ready**: Private DNS zones deployed and configured
- [ ] **Two-phase plan**: Using `foundryV22AccountOnly=true` then `false` for Standard setup
- [ ] **RBAC permissions**: Service principal/MI has required permissions
- [ ] **Wait task configured**: Pipeline includes wait for account caphost in Standard setup

## Output Validation

After deployment, check these outputs to confirm proper configuration:

```bash
# Check network setup type
az deployment sub show -n "deployment-name" \
  --query "properties.outputs.networkSetupType.value"

# Check agent subnet status
az deployment sub show -n "deployment-name" \
  --query "properties.outputs.agentSubnetStatus.value"

# Check capability host status
az deployment sub show -n "deployment-name" \
  --query "properties.outputs.capabilityHostStatus.value"

# Check for warnings
az deployment sub show -n "deployment-name" \
  --query "properties.outputs.caphostSetupWarning.value"
```

## Summary

✅ **Use Basic Setup** when:
- You don't need VNet integration for agents
- You want faster deployment
- Security requirements allow public endpoints

✅ **Use Standard Setup** when:
- You need full private networking
- Enterprise security is required
- You can accommodate two-phase deployment

⚠️ **Always validate** configuration using output properties before proceeding to next phase.
