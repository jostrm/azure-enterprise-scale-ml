@description('Specifies the objectId of the person that ordered the resources')
param userId string = ''

@description('Specifies the email address of the person that ordered the resources')
param userEmail string

@description('Additional optional Object ID of more people to access the Vm vmAdminLoginRole')
param additionalUserIds array

@description('Additional optional email address of more people to access the Vm vmAdminLoginRole')
param additionalUserEmails array

@description('This is the built-in Virtual Machine Administrator Login role. See https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles#virtual-machine-administrator-login')
resource VMAdminRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '1c0163c0-47e6-4577-8991-ea5c82e286e4'
}
param useAdGroups bool = false

var main_principal_2_array = array(userId)
//var all_principals = union(main_principal_2_array,additionalUserIds)
var main_email_2_array = array(userEmail)
//var all_emails = union(main_email_2_array,additionalUserEmails)

// Users or groups that will be assigned the VMAdminLogin role
resource vmAdminLoginRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(additionalUserIds)):if(!empty(additionalUserIds)){
  name: guid('${additionalUserIds[i]}-vmadminlogin-${resourceGroup().id}')
  properties: {
    roleDefinitionId: VMAdminRoleDefinition.id
    principalId: additionalUserIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Contributor to user ${additionalUserIds[i]} to get VMAdminLogin'
  }
}]

// Users - disabled if not using groups

resource vmAdminLoginRoleUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(main_principal_2_array)): if(useAdGroups==false && !empty(userId)){
  name: guid('${main_principal_2_array[i]}-vmadminlogin-${resourceGroup().id}')
  properties: {
    roleDefinitionId: VMAdminRoleDefinition.id
    principalId: main_principal_2_array[i]
    principalType:'User'
    description:'Contributor to user ${main_email_2_array[i]} to get VMAdminLogin'
  }
}]
