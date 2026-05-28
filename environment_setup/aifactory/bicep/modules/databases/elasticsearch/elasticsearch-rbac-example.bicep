// ================================================================
// EXAMPLE: How to deploy Elasticsearch with RBAC role assignments
// Mimics the pattern used in sqldatabaseRbac.bicep
// ================================================================

param location string = 'swedencentral'
param elasticEmail string = 'admin@example.com'
param elasticFirstName string = 'John'
param elasticLastName string = 'Doe'
param elasticCompanyName string = 'My Company'

// Arrays of principal IDs - replace with your actual Entra ID object IDs
param usersOrAdGroupArray array = [
  'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'  // Data Scientists Group
  'yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy'  // Admin User
]

param servicePrincipleAndMIArray array = [
  'zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz'  // Service Principal (App Registration)
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'  // User Assigned Managed Identity
]

// Built-in Azure RBAC role IDs (verified from Microsoft docs)
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles
var ownerRoleId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'          // Owner
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'   // Contributor
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'        // Reader

// Note: Elasticsearch/Elastic-specific roles may not exist as separate built-in roles
// Use Contributor for management access and Reader for read-only access

module elasticsearch './elasticsearch.bicep' = {
  name: 'elasticsearch-with-rbac'
  params: {
    name: 'es-myproject-sdc-001'
    location: location
    elasticEmail: elasticEmail
    elasticFirstName: elasticFirstName
    elasticLastName: elasticLastName
    elasticCompanyName: elasticCompanyName
    skuName: 'ess-consumption-2024_Monthly'
    deploymentSize: 'medium'
    monitoringEnabled: true
    
    // RBAC arrays - directly pass the arrays
    usersOrAdGroupArray: usersOrAdGroupArray
    servicePrincipleAndMIArray: servicePrincipleAndMIArray
    
    // Set to true if using Entra ID groups, false for individual users
    useAdGroups: true
    
    // Role assignments (can be different for users vs service principals)
    userRoleId: contributorRoleId       // Users/Groups get Contributor access
    spRoleId: ownerRoleId         // Service Principals/MI get Owner access
    
    // Private endpoint configuration
    createPrivateEndpoint: true
    vnetName: 'vnet-myproject-sdc'
    vnetResourceGroupName: 'rg-network-sdc'
    subnetNamePend: 'snet-privateendpoints'
    enablePublicGenAIAccess: false
    
    tags: {
      Environment: 'Production'
      Project: 'MyProject'
    }
  }
}

// ============== AVAILABLE AZURE BUILT-IN ROLE IDs ==============
// Standard Azure roles (verified):
// - Owner: 8e3af657-a8ff-443c-a75c-2fe8c4bcb635 (full access including RBAC)
// - Contributor: b24988ac-6180-42a0-ab88-20f7382dd24c (manage resources, no RBAC)
// - Reader: acdd72a7-3385-48ef-bd42-f606fba81ae7 (read-only access)
//
// Note: Elasticsearch-specific built-in roles do not appear to exist in Azure RBAC.
// Use Contributor for full management access and Reader for read-only access.

// ============== HOW TO CHECK FOR ELASTIC-SPECIFIC ROLES ==============
// Run this Azure CLI command to check if Elastic-specific roles exist:
// az role definition list --query "[?contains(roleName, 'Elastic')].{Name:roleName, Id:name}" -o table

// ============== PRINCIPAL TYPES ==============
// - usersOrAdGroupArray: Use for Entra ID users or groups (set useAdGroups appropriately)
// - servicePrincipleAndMIArray: Use for service principals (app registrations) and managed identities (UAMI/SAMI)

output elasticId string = elasticsearch.outputs.elasticResourceId
output elasticName string = elasticsearch.outputs.elasticName
output userRoleAssignments array = elasticsearch.outputs.userElasticRoleAssignments
output spRoleAssignments array = elasticsearch.outputs.spElasticRoleAssignments
