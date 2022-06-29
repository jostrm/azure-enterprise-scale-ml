@description('Specifies the objectId of the person that ordered the resources')
param userId string

@description('Specifies the email address of the person that ordered the resources')
param userEmail string

@description('Additional optional Object ID of more people to access the Vm vmAdminLoginRole')
param additionalUserIds array
@description('Additional optional email address of more people to access the Vm vmAdminLoginRole')
param additionalUserEmails array

var main_principal_2_array = array(userId)
var all_principals = union(main_principal_2_array,additionalUserIds)
var main_email_2_array = array(userEmail)
var all_emails = union(main_email_2_array,additionalUserEmails)

//  = [for i in range(0, length(all_principals)):{

resource vmAdminLoginRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_principals)):{
  name: guid('${all_principals[i]}-vmadminlogin-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/1c0163c0-47e6-4577-8991-ea5c82e286e4'
    principalId: all_principals[i]
    description:'Contributor to user ${all_emails[i]} to get VMAdminLogin'
  }
}]

/*
resource vmAdminLoginRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${userEmail}-vmadminlogin-${resourceGroup().name}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/1c0163c0-47e6-4577-8991-ea5c82e286e4'
    principalId: userId
  }
}
*/
