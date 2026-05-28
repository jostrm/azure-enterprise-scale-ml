// ================================================================
// ELASTICSEARCH (ELASTIC CLOUD) MODULE
// Deploys Azure Elastic Cloud integration
// ================================================================

@description('Elasticsearch monitor name')
param name string
// available regions for the Elasticsearch resource type is 'westus2,uksouth,eastus,eastus2,westeurope,francecentral,centralus,southcentralus,japaneast,southeastasia,australiaeast,northeurope,canadacentral,brazilsouth,southafricanorth,centralindia,spaincentral,germanywestcentral'.
@description('Azure region')
param location string

@description('Elastic Cloud SKU')
@allowed([
  'ess-consumption-2024_Monthly'
])
param skuName string = 'ess-consumption-2024_Monthly'

@description('Email associated with Elastic Cloud account')
param elasticEmail string

@description('First name of contact person')
param elasticFirstName string = 'AI'

@description('Last name of contact person')
param elasticLastName string = 'Factory'

@description('Company name')
param elasticCompanyName string = 'Organization'

@description('Enable monitoring')
param monitoringEnabled bool = true

@description('Deployment size')
@allowed([
  'small'
  'medium'
  'large'
])
param deploymentSize string = 'small'

@description('Tags for the resource')
param tags object = {}

@description('Enable public network access')
param enablePublicGenAIAccess bool = false

@description('Enable public access with network perimeter')
param enablePublicAccessWithPerimeter bool = false

@description('VNet name for private endpoint')
param vnetName string = ''

@description('VNet resource group name')
param vnetResourceGroupName string = ''

@description('Subnet name for private endpoint')
param subnetNamePend string = ''

@description('Create private endpoint')
param createPrivateEndpoint bool = true

@description('Array of principal IDs for users or AD groups')
param usersOrAdGroupArray array = []

@description('Array of principal IDs for service principals and managed identities')
param servicePrincipleAndMIArray array = []

@description('Use AD Groups instead of individual users')
param useAdGroups bool = false

@description('Role to assign to users/groups - defaults to Contributor')
param userRoleId string = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Contributor

@description('Role to assign to service principals/managed identities - defaults to Contributor')
param spRoleId string = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Contributor

// ============== LOCATION CONVERSION ==============
// Elasticsearch: If Sweden Central is chosen, use North Europe instead (Elasticsearch service requirement)
var elasticsearchLocation = (toLower(location) == 'swedencentral' || toLower(location) == 'sweden central') ? 'northeurope' : location

// ============== NAME CONVERSION ==============
// Convert naming convention: sdc (Sweden Central) -> neu (North Europe) for Elasticsearch resource
var elasticsearchName = (toLower(location) == 'swedencentral' || toLower(location) == 'sweden central') ? replace(name, 'sdc', 'neu') : name

// ============== RESOURCE DEPLOYMENT ==============

resource elastic 'Microsoft.Elastic/monitors@2024-03-01' = {
  name: elasticsearchName
  location: elasticsearchLocation
  sku: {
    name: skuName
  }
  properties: {
    monitoringStatus: monitoringEnabled ? 'Enabled' : 'Disabled'
    userInfo: {
      emailAddress: elasticEmail
      firstName: elasticFirstName
      lastName: elasticLastName
      companyName: elasticCompanyName
    }
  }
  tags: union(tags, {
    size: deploymentSize
    email: elasticEmail
  })
}

// ============== RBAC ROLE ASSIGNMENTS ==============
// Azure built-in roles (verified from Microsoft docs)
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles

// Standard Azure roles:
// Owner: 8e3af657-a8ff-443c-a75c-2fe8c4bcb635
// Contributor: b24988ac-6180-42a0-ab88-20f7382dd24c
// Reader: acdd72a7-3385-48ef-bd42-f606fba81ae7
//
// Note: Use Contributor for management access, Reader for read-only access
// Elasticsearch-specific built-in roles do not appear to exist in standard Azure RBAC

// Role assignments for users or AD groups
resource userElasticRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in usersOrAdGroupArray: {
  name: guid(elastic.id, userRoleId, principalId)
  scope: elastic
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', userRoleId)
    principalId: principalId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Role assignments for service principals and managed identities
resource spElasticRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in servicePrincipleAndMIArray: {
  name: guid(elastic.id, spRoleId, principalId)
  scope: elastic
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', spRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// ============== PRIVATE ENDPOINT ==============
// Note: Private endpoint must be in same location as VNet (original location, not converted)
var privateEndpointName = 'pend-${name}'
var privateLinkServiceConnectionName = 'plsc-${name}'
var groupId = 'es'

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (!enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && createPrivateEndpoint && !empty(vnetName)) {
  name: privateEndpointName
  location: location  // Keep original location for private endpoint (must match VNet location)
  tags: tags
  properties: {
    subnet: {
      id: resourceId(vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, subnetNamePend)
    }
    privateLinkServiceConnections: [
      {
        name: privateLinkServiceConnectionName
        properties: {
          privateLinkServiceId: elastic.id
          groupIds: [
            groupId
          ]
        }
      }
    ]
  }
}

// ============== OUTPUTS ==============

@description('Elasticsearch resource ID')
output elasticResourceId string = elastic.id

@description('Elasticsearch name (converted from sdc to neu if Sweden Central was specified)')
output elasticName string = elastic.name

@description('Actual location used for Elasticsearch (North Europe if Sweden Central was specified)')
output elasticsearchLocation string = elasticsearchLocation

@description('RBAC role assignments for users/groups')
output userElasticRoleAssignments array = [for i in range(0, length(usersOrAdGroupArray)): {
  id: userElasticRoleAssignment[i].id
  name: userElasticRoleAssignment[i].name
}]

@description('RBAC role assignments for service principals/managed identities')
output spElasticRoleAssignments array = [for i in range(0, length(servicePrincipleAndMIArray)): {
  id: spElasticRoleAssignment[i].id
  name: spElasticRoleAssignment[i].name
}]

@description('Private endpoint ID')
output privateEndpointId string = createPrivateEndpoint && !enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && !empty(vnetName) ? privateEndpoint.id : ''

@description('DNS configuration for private DNS zone linking')
output dnsConfig array = [
  {
    name: createPrivateEndpoint && !enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && !empty(vnetName) ? privateEndpointName : ''
    type: 'elastic'
    id: createPrivateEndpoint && !enablePublicGenAIAccess && !enablePublicAccessWithPerimeter && !empty(vnetName) ? elastic.id : ''
  }
]
