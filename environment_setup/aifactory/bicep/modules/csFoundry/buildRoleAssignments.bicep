// ================================================================
// BUILD ROLE ASSIGNMENTS MODULE
// This module builds role assignments array for AI Foundry services
// combining users/groups and service principals/managed identities
// Note: Service principle/MI's have higher privilege, 
// This follows the principle of least privilege where humans get user access
// and automated systems get contributor access for operations.
// ================================================================
/*
┌─────────────────────────────────────────────────────────┐
│  Dynamic Assignment Builder - AI Foundry 2025 example   │
│  ┌─────────────────────────────────────────────────────┐│
│  │  Builds roleAssignmentType[] array for AVM          ││
│  │  ┌─────────────────────────────────────────────────┐││
│  │  │  For Users/Groups:                              │ │
│  │  │  ├─ Cognitive Services User                     │ │
│  │  │  ├─ OpenAI User                                 │ │
│  │  │  └─ Cognitive Services Data Contributor (Preview)│ │
│  │  └─────────────────────────────────────────────────┘ │
│  │  ┌─────────────────────────────────────────────────┐ │
│  │  │  For Service Principals:                        │ │ 
│  │  │  ├─ Cognitive Services Contributor              │ │
│  │  │  ├─ OpenAI Contributor                          │ │
│  │  │  └─ Cognitive Services Data Contributor (Preview)│ │
│  │  └─────────────────────────────────────────────────┘ │
│  │  📤 Output: roleAssignmentType[] for AVM            
│  └─────────────────────────────────────────────────────┘
│  📝 Adapter pattern - converts to AVM format            
└─────────────────────────────────────────────────────────┘

*/
import { roleAssignmentType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'

@description('Array of user object IDs')
param userObjectIds array

@description('Array of service principal IDs')
param servicePrincipalIds array

@description('Cognitive Services User role ID')
param cognitiveServicesUserRoleId string

@description('Cognitive Services Contributor role ID')
param cognitiveServicesContributorRoleId string

@description('OpenAI User role ID')
param openAIUserRoleId string

@description('OpenAI Contributor role ID')
param openAIContributorRoleId string

@description('Azure AI Developer role ID - Required for Chat with Data scenarios')
param azureAIDeveloperRoleId string

@description('Key Vault Secrets User role ID - Required for Agent playground')
param keyVaultSecretsUserRoleId string = '4633458b-17de-408a-b874-0445c86b69e6'

@description('Key Vault Contributor role ID - Required for managing Agent secrets')
param keyVaultContributorRoleId string = 'f25e0fa2-a7c8-4377-a976-54943a77a395'

@description('Storage Blob Data Reader role ID - Required for AI Search to access storage')
param storageBlobDataReaderRoleId string = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

@description('Cognitive Services Data Contributor (Preview) role ID - Required for data plane operations on Foundry account')
param cognitiveServicesDataContributorRoleId string = '19c28022-e58e-450d-a464-0b2a53034789'

@description('Whether to use AD Groups')
param useAdGroups bool

param enableAISearch bool = false
param aiSearchPrincipalId string = ''


// Build role assignments for users/groups
var userRoleAssignments = [
  // Cognitive Services User roles for users/groups
  for userId in userObjectIds: {
    principalId: userId
    roleDefinitionIdOrName: cognitiveServicesUserRoleId
    principalType: useAdGroups ? 'Group' : 'User'
  }
]

var userOpenAIRoleAssignments = [
  // OpenAI User roles for users/groups
  for userId in userObjectIds: {
    principalId: userId
    roleDefinitionIdOrName: openAIUserRoleId
    principalType: useAdGroups ? 'Group' : 'User'
  }
]

// Build role assignments for service principals/managed identities
var spCognitiveRoleAssignments = [
  // Cognitive Services Contributor roles for service principals
  for spId in servicePrincipalIds: {
    principalId: spId
    roleDefinitionIdOrName: cognitiveServicesContributorRoleId
    principalType: 'ServicePrincipal'
  }
]

var spOpenAIRoleAssignments = [
  // OpenAI Contributor roles for service principals
  for spId in servicePrincipalIds: {
    principalId: spId
    roleDefinitionIdOrName: openAIContributorRoleId
    principalType: 'ServicePrincipal'
  }
]

// Build role assignments for AI Search if enabled
var aiSearchRoleAssignments = enableAISearch && !empty(aiSearchPrincipalId) ? [
  {
    principalId: aiSearchPrincipalId // AI Search service principal ID
    roleDefinitionIdOrName: cognitiveServicesContributorRoleId // Cognitive Services Contributor (original)
    principalType: 'ServicePrincipal'
  }
  {
    principalId: aiSearchPrincipalId // AI Search service principal ID
    roleDefinitionIdOrName: openAIContributorRoleId // Cognitive Services OpenAI Contributor
    principalType: 'ServicePrincipal'
  }
  {
    principalId: aiSearchPrincipalId // AI Search service principal ID
    roleDefinitionIdOrName: openAIUserRoleId // Cognitive Services OpenAI User (additional role for full functionality)
    principalType: 'ServicePrincipal'
  }
  {
    principalId: aiSearchPrincipalId // AI Search service principal ID
    roleDefinitionIdOrName: storageBlobDataReaderRoleId // Storage Blob Data Reader (required for storage access)
    principalType: 'ServicePrincipal'
  }
] : []

/* AI Developer is on Resource group scope, not Cognitive Services scope

// Build Azure AI Developer role assignments for users (required for Chat with Data)
var userAzureAIDeveloperRoleAssignments = [
  // Azure AI Developer roles for users/groups
  for userId in userObjectIds: {
    principalId: userId
    roleDefinitionIdOrName: azureAIDeveloperRoleId
    principalType: useAdGroups ? 'Group' : 'User'
  }
]

// Build Azure AI Developer role assignments for service principals
var spAzureAIDeveloperRoleAssignments = [
  // Azure AI Developer roles for service principals
  for spId in servicePrincipalIds: {
    principalId: spId
    roleDefinitionIdOrName: azureAIDeveloperRoleId
    principalType: 'ServicePrincipal'
  }
]
*/

// Build Cognitive Services Data Contributor (Preview) roles for users/groups
var userCognitiveServicesDataContributorRoleAssignments = [
  for userId in userObjectIds: {
    principalId: userId
    roleDefinitionIdOrName: cognitiveServicesDataContributorRoleId
    principalType: useAdGroups ? 'Group' : 'User'
  }
]

// Build Cognitive Services Data Contributor (Preview) roles for service principals/managed identities
var spCognitiveServicesDataContributorRoleAssignments = [
  for spId in servicePrincipalIds: {
    principalId: spId
    roleDefinitionIdOrName: cognitiveServicesDataContributorRoleId
    principalType: 'ServicePrincipal'
  }
]

// Build Key Vault roles for users (required for Agent playground)
var userKeyVaultRoleAssignments = [
  // Key Vault Secrets User roles for users/groups
  for userId in userObjectIds: {
    principalId: userId
    roleDefinitionIdOrName: keyVaultSecretsUserRoleId
    principalType: useAdGroups ? 'Group' : 'User'
  }
]

// Build Key Vault roles for service principals (required for Agent operations)
var spKeyVaultRoleAssignments = [
  // Key Vault Contributor roles for service principals
  for spId in servicePrincipalIds: {
    principalId: spId
    roleDefinitionIdOrName: keyVaultContributorRoleId
    principalType: 'ServicePrincipal'
  }
]

// Combine all role assignments
var allRoleAssignments = concat(
  userRoleAssignments,
  userOpenAIRoleAssignments,
  userCognitiveServicesDataContributorRoleAssignments, // Cognitive Services Data Contributor (Preview) for users
  //userAzureAIDeveloperRoleAssignments, // Add Azure AI Developer for users
  //spAzureAIDeveloperRoleAssignments, // Add Azure AI Developer for service principals
  userKeyVaultRoleAssignments, // Add Key Vault Secrets User for users
  spCognitiveRoleAssignments,
  spOpenAIRoleAssignments,
  spCognitiveServicesDataContributorRoleAssignments, // Cognitive Services Data Contributor (Preview) for SPs/MIs
  spKeyVaultRoleAssignments, // Add Key Vault Contributor for service principals
  aiSearchRoleAssignments
)

@description('Combined role assignments array')
output roleAssignments roleAssignmentType[] = allRoleAssignments
