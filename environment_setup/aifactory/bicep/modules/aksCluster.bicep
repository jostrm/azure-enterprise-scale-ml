// ============================================================================
// AKS Cluster Module
// ============================================================================
// This module creates an Azure Kubernetes Service (AKS) cluster with support for:
// - Private cluster configuration (API server accessible via private endpoint only)
// - Flexible outbound connectivity options:
//   * loadBalancer (default): Uses public IP for outbound traffic
//   * userDefinedRouting: Fully private - requires Azure Firewall/NAT Gateway + UDR
//   * managedNATGateway: Uses Azure-managed NAT Gateway
//   * userAssignedNATGateway: Uses user-managed NAT Gateway
//
// For fully private AKS without any public IP using userDefinedRouting:
// 1. Create a Route Table (UDR) with default route 0.0.0.0/0 -> Azure Firewall/NAT Gateway
// 2. Associate the route table with the AKS subnet (via subnet resource or separate module)
// 3. Set outboundType = 'userDefinedRouting' when calling this module
// 4. Pass the subnet ID (with route table already associated) in agentPoolProfiles
//
// Note: Route table association happens at the subnet level, not within this AKS resource.
// ============================================================================

@description('Specifies the name of the AKS cluster')
param name string
// ============== SKUs ==============
@description('Specifies the SKU name for the AKS cluster')
@allowed([
  'Base'
  'Standard'
])
param skuName string = 'Base'

@description('Specifies the SKU tier for the AKS cluster')
@allowed([
  'Free'
  'Standard'
  'Premium'
])
param skuTier string = 'Standard'
// ============== SKUs ==============
@description('Specifies the tags that should be applied to aks resources')
param tags object

@description('Specifies location were aks resources should be deployed')
param location string

@description('Specifies version of kubernetes on the AKS cluster')
param kubernetesVersion string // az aks get-versions --location westeurope --output table

@description('Specifies the DNS prefix for the AKS cluster')
param dnsPrefix string

@description('Specifies if RBAC permission model should be enabled or not')
param enableRbac bool = true
@description('Specifies if LOCAL accounts in kubernetes permission model should be enabled or not')
param disableLocalAccounts bool = false
@description('Specifies if AzureRbac accounts in kubernetes permission model should be enabled or not. 2022-11 needs to be false, since Azure ML')
param enableAzureRbac bool = false

@description('Specifies the outbound (egress) routing method for the AKS cluster')
@allowed([
  'loadBalancer'
  'userDefinedRouting'
  'managedNATGateway'
  'userAssignedNATGateway'
])
param outboundType string = 'loadBalancer' // 'userDefinedRouting' requires Azure Firewall/NAT Gateway + UDR for fully private AKS without public IP: https://learn.microsoft.com/en-us/azure/aks/egress-outboundtype

@description('Specifies agent pool profile settings in a array with hashmaps format')
param agentPoolProfiles array

@description('Specifies the name of the resource group that is used for node pool resources')
param nodeResourceGroup string

param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksExists bool = false
//param privateDNSZone string
//param authorizedIPRanges array

//skuName: 'basic' // basic -> 2023-02-01: 'base'
//skuTier: 'paid' // free, paid -> 2023-02-01: free, standard
// Microsoft.ContainerService/managedClusters@2021-03-01
resource aksCluster 'Microsoft.ContainerService/managedClusters@2025-05-01' = if(!aksExists) {
  name: name
  tags: tags
  location: location
  sku: {
    name: skuName
    tier: skuTier
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: dnsPrefix
    disableLocalAccounts:disableLocalAccounts
    enableRBAC: enableRbac
    agentPoolProfiles: agentPoolProfiles
    nodeResourceGroup: nodeResourceGroup
    networkProfile: {
      networkPlugin: 'azure'//'kubenet'
      outboundType: outboundType // 'userDefinedRouting' for fully private AKS without public IP
      serviceCidr: aksServiceCidr
      dnsServiceIP: aksDnsServiceIP
      loadBalancerSku: 'standard'
      loadBalancerProfile: outboundType == 'loadBalancer' ? {
        // Only configure load balancer when using loadBalancer outbound type
        managedOutboundIPs: {
          count: 1
        }
      } : null
    }
    apiServerAccessProfile: { // https://learn.microsoft.com/en-us/azure/aks/egress-outboundtype
      enablePrivateCluster: true // Private cluster - API server only accessible via private endpoint
    }
  }
  
}

output aksId string = aksCluster.id
