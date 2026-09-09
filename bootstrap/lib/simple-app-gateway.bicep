targetScope = 'resourceGroup'

param location string = resourceGroup().location
param gatewayName string
param vnetName string
param hostname string
param backendFqdn string
@description('Versionless Key Vault secret URI of an existing valid exportable PFX certificate; never a certificate value.')
@secure()
param certificateSecretId string
param costCenter string

var gatewayId = resourceId('Microsoft.Network/applicationGateways', gatewayName)
var identityId = resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', 'mi-${gatewayName}')
var vnetId = resourceId('Microsoft.Network/virtualNetworks', vnetName)

resource waf 'Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies@2024-05-01' = {
  name: 'waf-${gatewayName}'
  location: location
  tags: { CostCenter: costCenter }
  properties: {
    policySettings: {
      state: 'Enabled'
      mode: 'Prevention'
      requestBodyCheck: true
    }
    managedRules: {
      managedRuleSets: [{ ruleSetType: 'OWASP', ruleSetVersion: '3.2' }]
    }
  }
}

resource gateway 'Microsoft.Network/applicationGateways@2024-05-01' = {
  name: gatewayName
  location: location
  tags: { CostCenter: costCenter }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    sku: { name: 'WAF_v2', tier: 'WAF_v2' }
    autoscaleConfiguration: { minCapacity: 1, maxCapacity: 2 }
    firewallPolicy: { id: waf.id }
    forceFirewallPolicyAssociation: true
    enableHttp2: true
    sslPolicy: { policyType: 'Predefined', policyName: 'AppGwSslPolicy20220101S' }
    gatewayIPConfigurations: [
      { name: 'private-gateway', properties: { subnet: { id: '${vnetId}/subnets/snet-application-gateway' } } }
    ]
    frontendIPConfigurations: [
      {
        name: 'private-frontend'
        properties: {
          privateIPAddress: '172.16.2.10'
          privateIPAllocationMethod: 'Static'
          subnet: { id: '${vnetId}/subnets/snet-application-gateway' }
        }
      }
    ]
    frontendPorts: [{ name: 'https', properties: { port: 443 } }]
    sslCertificates: [{ name: 'frontend-tls', properties: { keyVaultSecretId: certificateSecretId } }]
    backendAddressPools: [
      { name: 'private-backend', properties: { backendAddresses: [{ fqdn: backendFqdn }] } }
    ]
    probes: [
      {
        name: 'https-health'
        properties: {
          protocol: 'Https'
          host: backendFqdn
          path: '/'
          interval: 30
          timeout: 30
          unhealthyThreshold: 3
          match: { statusCodes: ['200-399'] }
        }
      }
    ]
    backendHttpSettingsCollection: [
      {
        name: 'private-https'
        properties: {
          port: 443
          protocol: 'Https'
          cookieBasedAffinity: 'Disabled'
          requestTimeout: 30
          hostName: backendFqdn
          probe: { id: '${gatewayId}/probes/https-health' }
        }
      }
    ]
    httpListeners: [
      {
        name: 'private-https'
        properties: {
          protocol: 'Https'
          hostName: hostname
          requireServerNameIndication: true
          frontendIPConfiguration: { id: '${gatewayId}/frontendIPConfigurations/private-frontend' }
          frontendPort: { id: '${gatewayId}/frontendPorts/https' }
          sslCertificate: { id: '${gatewayId}/sslCertificates/frontend-tls' }
        }
      }
    ]
    requestRoutingRules: [
      {
        name: 'private-https'
        properties: {
          priority: 100
          ruleType: 'Basic'
          httpListener: { id: '${gatewayId}/httpListeners/private-https' }
          backendAddressPool: { id: '${gatewayId}/backendAddressPools/private-backend' }
          backendHttpSettings: { id: '${gatewayId}/backendHttpSettingsCollection/private-https' }
        }
      }
    ]
  }
}

resource frontendZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: hostname
  location: 'global'
  tags: { CostCenter: costCenter }
}

resource frontendLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: frontendZone
  name: 'application-gateway'
  location: 'global'
  properties: { virtualNetwork: { id: vnetId }, registrationEnabled: false }
}

resource frontendRecord 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: frontendZone
  name: '@'
  properties: { ttl: 300, aRecords: [{ ipv4Address: '172.16.2.10' }] }
}

output gatewayId string = gateway.id
output endpoint string = 'https://${hostname}'
