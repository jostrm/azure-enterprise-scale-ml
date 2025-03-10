@description('Specifies the objectId of the person that ordered the resources')
param userId string

@description('Specifies the email address of the person that ordered the resources')
param userEmail string
param useAdGroups bool = false

@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource contributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
@description('Additional optional email adress of more people to access the Resource group')
param additionalUserEmails array

var main_principal_2_array = array(userId)
//var all_principals = union(main_principal_2_array,additionalUserIds)

var main_email_2_array = array(userEmail)
var all_emails = union(main_email_2_array,additionalUserEmails)

resource contributorRole2userOrGroup 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(additionalUserIds)):{
  name: guid('${additionalUserIds[i]}-contributor-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: additionalUserIds[i]
    principalType:useAdGroups? 'Group':'User'
    description: 'Contributor to user ${additionalUserEmails[i]} to get Contributor on resource group: ${resourceGroup().name}'
  }
}]

resource contributorRole2user 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(main_principal_2_array)): if(useAdGroups==false){
  name: guid('${main_principal_2_array[i]}-contributor-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: main_principal_2_array[i]
    principalType:'User'
    description: 'Contributor to user ${main_email_2_array[i]} to get Contributor on resource group: ${resourceGroup().name}'
  }
}]

