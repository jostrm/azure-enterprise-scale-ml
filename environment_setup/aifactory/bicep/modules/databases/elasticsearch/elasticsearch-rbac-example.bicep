// ================================================================
// EXAMPLE: How to deploy Elasticsearch with RBAC role assignments
// Mimics the pattern used in sqldatabaseRbac.bicep
// ================================================================

param location string = 'swedencentral'
param elasticEmail string = 'admin@example.com'

// Example: Entra ID Group, Users, Service Principals, and Managed Identities Object IDs
param dataScientistsGroupId string = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
param adminUserId string = 'yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy'
param appServicePrincipalId string = 'zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz'
param uamiPrincipalId string = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

// Built-in Azure RBAC role IDs
var elasticAdminRoleId = 'bfb6c928-ebaa-4e44-bd4a-7468c1c7b2da'  // Elastic Admin
var elasticReaderRoleId = 'e71e9d0e-0384-4d07-b5eb-d3154b9a6a56' // Elastic Reader
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'   // Contributor
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'        // Reader

module elasticsearch './elasticsearch.bicep' = {
  name: 'elasticsearch-with-rbac'
  params: {
    name: 'es-myproject-sdc-001'
    location: location
    elasticEmail: elasticEmail
    skuName: 'ess-consumption-2024_Monthly'
    deploymentSize: 'medium'
    monitoringEnabled: true
    
    // RBAC for users or Entra ID groups
    usersOrAdGroupArray: [
      dataScientistsGroupId  // Entra ID Group
      adminUserId            // Individual User
    ]
    
    // RBAC for service principals and managed identities (UAMI/SAMI)
    servicePrincipleAndMIArray: [
      appServicePrincipalId  // Service Principal (App Registration)
      uamiPrincipalId        // User Assigned Managed Identity
    ]
    
    // Set to true if using Entra ID groups, false for individual users
    useAdGroups: true
    
    // Role assignments (can be different for users vs service principals)
    userRoleId: elasticAdminRoleId      // Users/Groups get Elastic Admin
    spRoleId: contributorRoleId         // Service Principals/MI get Contributor
    
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
// Elastic-specific roles:
// - Elastic Admin: bfb6c928-ebaa-4e44-bd4a-7468c1c7b2da
// - Elastic Reader: e71e9d0e-0384-4d07-b5eb-d3154b9a6a56
//
// General Azure roles:
// - Owner: 8e3af657-a8ff-443c-a75c-2fe8c4bcb635
// - Contributor: b24988ac-6180-42a0-ab88-20f7382dd24c
// - Reader: acdd72a7-3385-48ef-bd42-f606fba81ae7

// ============== PRINCIPAL TYPES ==============
// - usersOrAdGroupArray: Use for Entra ID users or groups (set useAdGroups appropriately)
// - servicePrincipleAndMIArray: Use for service principals (app registrations) and managed identities (UAMI/SAMI)

output elasticId string = elasticsearch.outputs.elasticResourceId
output elasticName string = elasticsearch.outputs.elasticName
output userRoleAssignments array = elasticsearch.outputs.userElasticRoleAssignments
output spRoleAssignments array = elasticsearch.outputs.spElasticRoleAssignments
