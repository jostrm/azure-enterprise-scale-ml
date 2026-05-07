// ============================================================================
// Policy Exemption — Foundry ACA Subnets
// ============================================================================
// Scope: deployed at resource group level (VNet RG) by the caller.
//
// WHY: Azure AI Foundry Standard Agent injects a delegated NIC into the ACA
// subnet (snt-*-aca*) during provisioning. Any deployIfNotExists (DINE) or
// auditIfNotExists policy that fires a remediation task on that subnet while
// Foundry is mid-injection will mutate the subnet and cause a 409 conflict,
// leaving the capability host in a broken state.
//
// FIX: A policy exemption scoped to the VNet RG suppresses all DINE/Audit
// remediation on every resource in that RG (including the subnet) for the
// specified policy assignments. The five Foundry-safety guarantees are then
// met deterministically:
//   ✅ Subnet created once
//   ✅ Delegation set at creation
//   ✅ NSG / UDR attached at creation
//   ✅ Policy exempted or guarded   ← this module
//   ✅ RP has Reader on VNet RG
//
// HOW TO FIND RELEVANT ASSIGNMENT IDs (run before deployment):
//   az policy assignment list \
//     --scope /subscriptions/<sub>/resourceGroups/<vnet-rg> \
//     --query "[].id" -o tsv
// Then filter the output for assignments whose policy definitions have
// effect == deployIfNotExists or auditIfNotExists and target subnets / VNets.
// ============================================================================

targetScope = 'resourceGroup'

@description('''
Array of policy assignment resource IDs whose effect is deployIfNotExists or
auditIfNotExists and that target VNet / subnet resources. One exemption is
created per entry, all scoped to this resource group (the VNet RG).

Example value:
  [
    "/subscriptions/<sub>/providers/Microsoft.Authorization/policyAssignments/Deny-DINE-Subnets",
    "/providers/Microsoft.Management/managementGroups/<mg>/providers/Microsoft.Authorization/policyAssignments/Deploy-DINE-Network"
  ]

Leave empty ([]) to skip exemption creation (no-ALZ or greenfield environments).
''')
param policyAssignmentIds string[] = []

@description('''
Optional: list of policyDefinitionReferenceIds within an initiative (policy set)
to restrict the exemption to only those DINE / auditIfNotExists members.
Leave empty ([]) to exempt the entire assignment.
Applies equally to all entries in policyAssignmentIds.
''')
param policyDefinitionReferenceIds string[] = []

@description('Human-readable justification stored on every exemption resource.')
param exemptionDescription string = 'Foundry Standard Agent requires subnet immutability during network injection into snt-*-aca* subnets. deployIfNotExists and auditIfNotExists remediation tasks cause 409 conflicts during capability-host provisioning. Exemption is scoped to the VNet resource group.'

// One exemption per assignment ID — name is deterministic so re-deployments are idempotent.
resource exemptions 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = [for assignmentId in policyAssignmentIds: {
  name: take('foundry-aca-subnet-${uniqueString(assignmentId)}', 64)
  properties: {
    policyAssignmentId: assignmentId
    policyDefinitionReferenceIds: policyDefinitionReferenceIds
    exemptionCategory: 'Waiver'
    displayName: 'Foundry ACA subnet exemption — ${last(split(assignmentId, '/'))}'
    description: exemptionDescription
  }
}]

@description('Number of policy exemptions created.')
output exemptionCount int = length(policyAssignmentIds)
