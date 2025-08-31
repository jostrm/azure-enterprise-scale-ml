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
│  │  │  └─ OpenAI User                                 │ │
│  │  └─────────────────────────────────────────────────┘ │
│  │  ┌─────────────────────────────────────────────────┐ │
│  │  │  For Service Principals:                        │ │ 
│  │  │  ├─ Cognitive Services Contributor              │ │
│  │  │  └─ OpenAI Contributor                          │ │
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
    roleDefinitionIdOrName: cognitiveServicesContributorRoleId // Cognitive Services OpenAI Contributor
    principalType: 'ServicePrincipal'
  }
] : []

// Combine all role assignments
var allRoleAssignments = concat(
  userRoleAssignments,
  userOpenAIRoleAssignments,
  spCognitiveRoleAssignments,
  spOpenAIRoleAssignments,
  aiSearchRoleAssignments
)

@description('Combined role assignments array')
output roleAssignments roleAssignmentType[] = allRoleAssignments
