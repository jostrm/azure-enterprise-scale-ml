@description('Gets the existing IP rules from a container registry')
param containerRegistryName string

resource existingAcr 'Microsoft.ContainerRegistry/registries@2024-11-01-preview' existing = {
  name: containerRegistryName
}

output ipRules array = existingAcr.properties.?networkRuleSet.?ipRules ?? []
