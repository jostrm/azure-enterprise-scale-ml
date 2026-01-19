// Module to get existing ACR encryption configuration
param containerRegistryName string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

output hasEncryption bool = acr.properties.encryption != null && acr.properties.encryption.status == 'enabled'
output keyVaultPropertiesIdentity string = acr.properties.encryption != null && acr.properties.encryption.keyVaultProperties != null ? acr.properties.encryption.keyVaultProperties.identity : ''
output keyIdentifier string = acr.properties.encryption != null && acr.properties.encryption.keyVaultProperties != null ? acr.properties.encryption.keyVaultProperties.keyIdentifier : ''
