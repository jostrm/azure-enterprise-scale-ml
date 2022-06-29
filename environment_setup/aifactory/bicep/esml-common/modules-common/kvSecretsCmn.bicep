@description('Common KEYVAULT for ESML coreteam')
param keyvaultName string

@description('secret name of App ID for service principle')
param esmlCommonSpID string = 'esml-common-sp-id'
@secure()
@description('value of service principle ID')
param esmlCommonSpIDSecret string

@description('secret name of OBJECT ID for service principle')
param esmlCommonSpOID string = 'esml-common-sp-oid'
@secure()
@description('value of service principle OBJECT ID')
param esmlCommonSpOIDValue string

@description('secret name of for service principle App ID')
param esmlCommonSpSecret string = 'esml-common-sp-secret'
@secure()
@description('value of service principle secret')
param esmlCommonSpSecretValue string

@description('value of Tenant ID')
param esmlTenantID string = 'esml-tenant-id'

@description('secret value of Tenant ID')
param esmlTenantIDSecret string = subscription().tenantId

@description('secret value of Subscripton ID of current ESML environment')
param esmlSubscriptionID string = 'esml-subscription-id'

@description('secret value of Subscripton ID of current ESML environment')
param esmlSubscriptionIDSecret string = subscription().subscriptionId

@description('default keyvault secret expiration date in inteter, EPOC, seconds after 1970')
param expiration_date_default_2025_01_10_epoch int = 1736467877

resource kvSecretESMLCommonSpID 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlCommonSpID}'
  properties: {
    value:esmlCommonSpIDSecret
    contentType: 'ESML generated - Common service principle App ID'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// SP OID
resource kvSecretESMLCommonSpOID 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlCommonSpOID}'
  properties: {
    value:esmlCommonSpOIDValue
    contentType: 'ESML generated - Common service principle OBJECT ID, for RBAC in BICEP or ACL on lake'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}

// SP SECRET
resource kvSecretESMLCommonSpSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlCommonSpSecret}'
  properties: {
    value:esmlCommonSpSecretValue
    contentType: 'ESML generated - Common service principle secret'
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
