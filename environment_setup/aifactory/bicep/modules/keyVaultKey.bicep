@description('The name of the Key Vault')
param keyVaultName string

@description('The name of the key to create')
param keyName string

@description('The type of the key')
@allowed(['RSA', 'EC'])
param kty string = 'RSA'

@description('The key size in bits. For RSA: 2048, 3072, or 4096. For EC: P-256, P-384, P-521.')
param keySize int = 2048

@description('The curve name for EC keys. Allowed values: P-256, P-384, P-521.')
@allowed(['P-256', 'P-384', 'P-521', ''])
param curveName string = ''

@description('The key operations.')
param keyOps array = [
  'encrypt'
  'decrypt'
  'sign'
  'verify'
  'wrapKey'
  'unwrapKey'
]

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource key 'Microsoft.KeyVault/vaults/keys@2023-07-01' = {
  parent: keyVault
  name: keyName
  properties: {
    kty: kty
    keySize: kty == 'RSA' ? keySize : null
    curveName: kty == 'EC' ? (empty(curveName) ? 'P-256' : curveName) : null
    keyOps: keyOps
    attributes: {
      enabled: true
    }
  }
}

output keyName string = key.name
output keyUri string = key.properties.keyUri
output keyUriWithVersion string = key.properties.keyUriWithVersion
