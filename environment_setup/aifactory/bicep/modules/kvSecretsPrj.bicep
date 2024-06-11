@description(' KEYVAULT for ESML coreteam or PROJECT team')
param keyvaultName string

// is added manually by AAD admin in project KV
@description('secret name of App ID for service principle')
param spIDKey string = 'esml-project-sp-id'
@secure()
@description('value of service principle ID')
param spAppIDValue string //= 'Added from ADO variable, or manually'

@description('secret name of for service principle App ID')
param spSecret string = 'esml-project-sp-secret'
@secure()
@description('value of service principle secret')
param spSecretValue string //'Is added manually by AAD admin'

@description('secret value of Tenant ID')
param esmlTenantID string = 'esml-tenant-id'

//@secure()
@description('secret value of Tenant ID')
param esmlTenantIDSecret string = subscription().tenantId

@description('secret value of Subscripton ID of current ESML environment')
param esmlSubscriptionID string = 'esml-subscription-id'
//@secure()
@description('secret value of Subscripton ID of current ESML environment')
param esmlSubscriptionIDSecret string = subscription().subscriptionId

@description('default keyvault secret expiration date in inteter, EPOC, seconds after 1970')
param expiration_date_default_2025_01_10_epoch int = 1736467877 // 2025 if created 2022 (3yr)

@description('secret name of Object ID for service principle')
param spOIDKey string = 'esml-project-sp-oid'
@secure()
@description('value of service principle ObjectID')
param spOIDValue string //= 'Added from ADO variable, or manually'

var esml_project_dbx_token_key = 'esml-project-dbx-token'

// SP APP ID - from ADO Variable
resource kvSecretDatabricksToken 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esml_project_dbx_token_key}'
  properties: {
    value:'TODO Databricks token'
    contentType: 'ESML generated. TODO:Databricks token - needed for Azure ML pipelines with DatabricksSteps'//'ESML generated dummy.SP-AppId. AAD-admin need to add real service-principle AppID guid.'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// SP APP ID - from ADO Variable
resource kvSecretspID 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${spIDKey}'
  properties: {
    value:spAppIDValue
    contentType: 'Application ID of service principle'//'ESML generated dummy.SP-AppId. AAD-admin need to add real service-principle AppID guid.'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// SP SECRET
resource kvSecretspIDValue 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${spSecret}'
  properties: {
    value:spSecretValue
    contentType: 'ESML generated. From seeding keyvalt (esml-project-sp-secret). Project specific service principle secret'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// SP OBJECT ID - from ADO Variable
resource kvSecretspOID 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${spOIDKey}'
  properties: {
    value:spOIDValue
    contentType: 'OBJECT ID of service principle'//'ESML generated dummy.SP-AppId. AAD-admin need to add real service-principle AppID guid.'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// tenant id
resource kvSecretTenatID 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlTenantID}'
  properties: {
    value:esmlTenantIDSecret
    contentType:'ESML generated - tenant ID'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// subscription id
resource kvSecretSubscriptionID 'Microsoft.KeyVault/vaults/secrets@2021-10-01' = {
  name: '${keyvaultName}/${esmlSubscriptionID}'
  properties: {
    value:esmlSubscriptionIDSecret
    contentType: 'ESML generated - Subscription ID for current ESML environment'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
    
  }
}

/*
param esmlCommonLakeSaKey string = 'esml-common-lake-saKey'
@secure()
param esmlCommonLakeSaKeySecret string = ''
*/

/*
resource kvSecretESMLCommonDatalakeSaKey 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlCommonLakeSaKey}'
  properties: {
    value:esmlCommonLakeSaKeySecret
    contentType: 'ESML generated - storage account key. ESML CoreTeam admin to mount Databricks.'
  }
}
*/
