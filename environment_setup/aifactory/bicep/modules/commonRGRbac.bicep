param commonRGId string
param userObjectIds array
@secure()
param servicePrincipleObjectId string

// Container Registry (EP, WebApp, Azure Function)
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec' // SP, user -> RG
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // EP, App service or Function app -> RG

// --------------- COMMON RESOURCE GROUP ---------------- //
@description('Role Assignment for ResoureGroup: acrPushRoleId for users.')
resource acrPushCmn 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(userObjectIds)):{
  name: guid(commonRGId, acrPushRoleId, userObjectIds[i])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: userObjectIds[i]
    principalType: 'User'
    description:'030: acrPush role on RG to USER with OID  ${userObjectIds[i]} for RG: ${commonRGId}'
  }
  scope:resourceGroup()
}]

resource acrPushSPCmn 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(commonRGId, acrPushRoleId, servicePrincipleObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: servicePrincipleObjectId
    principalType: 'ServicePrincipal'
    description:'acrPush role to project service principal OID:${servicePrincipleObjectId} for RG: ${commonRGId}'
  }
  scope:resourceGroup()
}

