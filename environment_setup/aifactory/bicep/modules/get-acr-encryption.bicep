// Module to get existing ACR encryption configuration
param containerRegistryName string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

// Defensive guards because some API versions only return encryption.status when CMK is disabled
var encryption = acr.properties.encryption ?? {}

output hasEncryption bool = contains(encryption, 'status') && encryption.status == 'enabled'
output keyVaultPropertiesIdentity string = contains(encryption, 'keyVaultProperties') && contains(encryption.keyVaultProperties, 'identity') ? encryption.keyVaultProperties.identity : ''
output keyIdentifier string = contains(encryption, 'keyVaultProperties') && contains(encryption.keyVaultProperties, 'keyIdentifier') ? encryption.keyVaultProperties.keyIdentifier : ''
