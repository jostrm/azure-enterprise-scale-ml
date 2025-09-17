@description('Specifies the name of the new machine learning studio resources')
param name string
param uniqueDepl string
param uniqueSalt5char string
param locationSuffix string
param aifactorySuffix string
param projectName string
param projectNumber string
param location string
param env string
param aksSubnetId string
@description('Subnet name for aks')
param aksSubnetName string
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'

@description('AKS own SSL on private cluster. MS auto SSL is not possible since private cluster')
param ownSSL string = 'disabled' //enabled
param aksCert string = ''
param aksCname string = ''
param aksCertKey string = ''
param aksSSLOverwriteExistingDomain bool = false
param aksSSLstatus string = ''

@description('Specifies the skuname of the machine learning studio')
param skuName string
@description('Specifies the sku tier of the machine learning studio')
param skuTier string
@description('Specifies the tags that should be applied to machine learning studio resources')
param tags object
@description('(Required) Specifies the private endpoint name')
param privateEndpointName string
@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetId string
@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
@description('Resource name ID on DnsZone')
param amlPrivateDnsZoneID string
@description('Resource name ID on DnsZone')
param notebookPrivateDnsZoneID string
@description('AKS Kubernetes version and AgentPool orchestrator version')
param kubernetesVersionAndOrchestrator string
@description('Azure ML allowPublicAccessWhenBehindVnet')
param allowPublicAccessWhenBehindVnet bool = false
@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool = false
var subnetRef = '${vnetId}/subnets/${subnetName}'

// See Azure VM Sku: https://docs.microsoft.com/en-us/azure/virtual-machines/sizes-general

@description('DEV default VM size for the default compute cluster: STANDARD_D3')
param amlComputeDefaultVmSize_dev string// 'Standard_D3_v2' //// STANDARD_D4(4,16b ram) Standard_D14 (16 cores,112 ram) 
@description('TestProd default VM size for the default compute cluster: STANDARD_D4')
param amlComputeDefaultVmSize_testProd string // 'STANDARD_D4' //// STANDARD_D4(4,16b ram) Standard_D14 (16 cores,112 ram) 
@description('Dev Max nodes: 0-Max')
param amlComputeMaxNodex_dev int
@description('TestProd Max nodes: 0-Max')
param amlComputeMaxNodex_testProd int
@description('DEV default  VM size for the default AKS cluster:Standard_D12. More: Standard_D3_v2(4,14)')
param aksVmSku_dev string
@description('TestProd default  VM size for the default AKS cluster:Standard_D12(4,28,200GB)')
param aksVmSku_testProd string
@description('Dev Agentpool agents/nodes: 1 as default for Dev')
param aksNodes_dev int
@description('Dev Agentpool agents/nodes: 3 as default for Test or Prod')
param aksNodes_testProd int
@description('DEV default VM size for the default Compute Instance cluster:Standard_D4_v3(4,16,100)')
param ciVmSku_dev string
@description('TestProd default VM size for the default Compute Instance cluster:Standard_D4_v3. More: Standard_D14 (16 cores,112 ram)')
param ciVmSku_testProd string
param ipRules array = []
param saName string
param kvName string
param acrName string
param acrRGName string
param appInsightsName string
param ipWhitelist_array array = []
param enablePublicAccessWithPerimeter bool = false
import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?

var aiFactoryNumber = substring(aifactorySuffix,1,3) // -001 to 001
var aml_create_ci=false

resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: saName
}

resource existingKeyvault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: kvName
}
resource existingAppInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
  scope: resourceGroup(acrRGName)
}
var formattedUserAssignedIdentities = reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }
var identity = !empty(managedIdentities)
  ? {
      type: (managedIdentities.?systemAssigned ?? false)
        ? (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'UserAssigned' : 'None')
      userAssignedIdentities: !empty(formattedUserAssignedIdentities) ? formattedUserAssignedIdentities : null
    }
  : {type:'SystemAssigned'}

// 2025-08 <- 2024-10-01-preview
// 2025-08 -> 2025-07-01-preview
resource azureMLv2Dev 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' = if(env == 'dev') {
  name: name
  location: location
  kind:'Default'
  sku: {
    name: skuName
    tier: skuTier
  }
  identity:identity
  tags: tags
  properties: {
    allowRoleAssignmentOnRG: true
    imageBuildCompute: '${name}/p${projectNumber}-m01${locationSuffix}-${env}'
    friendlyName: name
    description: 'Azure Machine Learning v2, managed networking, not using legacy V1 mode'
    // dependent resources
    storageAccount: existingStorageAccount.id
    keyVault: existingKeyvault.id
    containerRegistry: existingAcr.id
    applicationInsights: existingAppInsights.id

    // configuration
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false
    provisionNetworkNow: true
    enableDataIsolation: false
    v1LegacyMode:false

    // network settings
    publicNetworkAccess: (!empty(ipWhitelist_array) || enablePublicAccessWithPerimeter)? 'Enabled': 'Disabled' // Disabled:The workspace can only be accessed through private endpoints. No IP Whitelisting possible.
    allowPublicAccessWhenBehindVnet: (!empty(ipWhitelist_array) || enablePublicAccessWithPerimeter)? true: allowPublicAccessWhenBehindVnet // Allows controlled public access through IP allow lists while maintaining VNet integration
    managedNetwork: {
      firewallSku:'Basic' // 'Standard'
      isolationMode:'AllowInternetOutBound' //'AllowInternetOutBound': 'AllowOnlyApprovedOutbound'
      #disable-next-line BCP037
      enableNetworkMonitor:false
    }
    //softDeleteEnabled: false
    ipAllowlist: (allowPublicAccessWhenBehindVnet && !empty(ipWhitelist_array)) ? ipWhitelist_array: null
    networkAcls: (allowPublicAccessWhenBehindVnet && !empty(ipWhitelist_array)) ? {
      defaultAction: 'Deny' // TODO: DTO error for some regions if not 'Allow'
      ipRules: ipRules
    } : null
    
  }
  dependsOn:[
    aksDev
  ]
}
resource amlv2TestProd 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview'  = if(env == 'test' || env == 'prod') {
  name: name
  location: location
  kind:'Default'
  sku: {
    name: skuName
    tier: skuTier
  }
  identity: identity
  tags: tags
  properties: {
    allowRoleAssignmentOnRG: true
    imageBuildCompute: '${name}/p${projectNumber}-m01${locationSuffix}-${env}'
    friendlyName: name
    description: 'Azure Machine Learning v2, managed networking, not using legacy V1 mode'
    // dependent resources
    storageAccount: existingStorageAccount.id
    keyVault: existingKeyvault.id
    containerRegistry: existingAcr.id
    applicationInsights: existingAppInsights.id

    // configuration
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false
    provisionNetworkNow: true
    enableDataIsolation: false
    v1LegacyMode:false

    // network settings
    publicNetworkAccess: (!empty(ipWhitelist_array) || enablePublicAccessWithPerimeter)? 'Enabled': 'Disabled' // Disabled:The workspace can only be accessed through private endpoints. No IP Whitelisting possible.
    allowPublicAccessWhenBehindVnet: (!empty(ipWhitelist_array) || enablePublicAccessWithPerimeter)? true: allowPublicAccessWhenBehindVnet // Allows controlled public access through IP allow lists while maintaining VNet integration
    managedNetwork: {
      firewallSku:'Basic' // 'Standard'
      isolationMode:'AllowInternetOutBound' //'AllowInternetOutBound': 'AllowOnlyApprovedOutbound'
      #disable-next-line BCP037
      enableNetworkMonitor:false
    }
    //softDeleteEnabled: false
    ipAllowlist: (allowPublicAccessWhenBehindVnet && !empty(ipWhitelist_array)) ? ipWhitelist_array: null
    networkAcls: (allowPublicAccessWhenBehindVnet && !empty(ipWhitelist_array)) ? {
      defaultAction: 'Deny' // TODO: DTO error for some regions if not 'Allow'
      ipRules: ipRules
    } : null
    
  }
  dependsOn:[
    aksTestProd
  ]
}

var pendName = '${name}-pend'
module machineLearningPrivateEndpoint 'machinelearningNetwork.bicep' = if(!enablePublicAccessWithPerimeter) {
  name: take('Amlv2-NW${uniqueDepl}',64)
  scope: resourceGroup()
  params: {
    location: location
    tags: tags
    workspaceArmId: (env=='dev')? azureMLv2Dev.id: amlv2TestProd.id
    subnetId: subnetRef
    machineLearningPleName: pendName
    amlPrivateDnsZoneID: amlPrivateDnsZoneID
    notebookPrivateDnsZoneID: notebookPrivateDnsZoneID
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    ...(env == 'dev' ? [azureMLv2Dev] : [amlv2TestProd])
  ]
}

var aksName = 'aks${projectNumber}-${locationSuffix}-${env}' // aks001-weu-prod (20/16) VS aks001-weu-prod (16/16)
var nodeResourceGroupName = 'aks-${resourceGroup().name}' // aks-abc-def-esml-project001-weu-dev-003-rg (unique within subscription)

module aksDev 'aksCluster.bicep'  = if(env == 'dev') {
  name: take('Amlv2-AKS-D${uniqueDepl}',64)
  params: {
    name: aksName // esml001-weu-prod
    tags: {} // NB! Error if tags is more than 15, since managed RG inherits them
    location: location
    kubernetesVersion: kubernetesVersionAndOrchestrator // az aks get-versions --location westeurope --output table    // in Westeurope '1.21.2'  is not allowed/supported
    dnsPrefix: '${aksName}-dns'
    enableRbac: true
    nodeResourceGroup: nodeResourceGroupName // 'esml-${replace(projectName, 'prj', 'project')}-aksnode-${env}-rg'
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr:aksServiceCidr
    agentPoolProfiles: [
      {
        name: toLower('agentpool')
        count: aksNodes_dev
        vmSize: aksVmSku_dev
        osType: 'Linux'
        osSKU: 'Ubuntu'
        mode: 'System'
        vnetSubnetID: aksSubnetId
        type: 'VirtualMachineScaleSets'
        maxPods: 30 //110  total maxPods(maxPods per node * node count), the total maxPods(10 * 1) should be larger than 30.
        orchestratorVersion: kubernetesVersionAndOrchestrator // in Westeurope '1.21.2'  is not allowed/supported
        osDiskSizeGB: 128
      }
    ]
  }
}

module aksTestProd 'aksCluster.bicep'  = if(env == 'test' || env == 'prod') {
  name: take('Amlv2-AKS-TP${uniqueDepl}',64)
  params: {
    name: aksName // 'aks${projectNumber}-${locationSuffix}-${env}$'
    tags: {} // NB! Error if tags is more than 15, since managed RG inherits them
    location: location
    kubernetesVersion: kubernetesVersionAndOrchestrator // az aks get-versions --location westeurope --output table  1.22.6 and 1.23.3(preview) // in Westeurope '1.21.2'  is not allowed/supported
    dnsPrefix: '${aksName}-dns' // 'aks-${projectName}-${locationSuffix}-${env}${prjResourceSuffix}'
    enableRbac: true
    nodeResourceGroup: nodeResourceGroupName //'esml-${replace(projectName, 'prj', 'project')}-aksnode-${env}-rg'
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr:aksServiceCidr
    agentPoolProfiles: [
      {
        name: 'agentpool'
        count: aksNodes_testProd
        vmSize: aksVmSku_testProd
        osType: 'Linux'
        osSKU: 'Ubuntu'
        mode: 'System'
        vnetSubnetID: aksSubnetId
        type: 'VirtualMachineScaleSets'
        maxPods: 30 // maxPods: 110
        orchestratorVersion: kubernetesVersionAndOrchestrator // in Westeurope '1.21.2'  is not allowed/supported
      }
    ]
  }

}

//AKS attach compute PRIVATE cluster, without SSL
//Microsoft.MachineLearningServices/workspaces/computes@2022-10-01
resource machineLearningCompute 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01-preview' = if(ownSSL == 'disabled' && env=='dev') {	
  name: aksName
  parent: azureMLv2Dev
  location: location
  properties: {
    computeType: 'AKS'
    computeLocation: location
    description:'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'
    #disable-next-line BCP318
    resourceId: ((env =='dev') ? aksDev.outputs.aksId : aksTestProd.outputs.aksId)  
    properties: {
      agentCount:  ((env =='dev') ? 1 :  3)
      clusterPurpose: ((env =='dev') ? 'DevTest' : 'FastProd') // 'DenseProd' also available
      agentVmSize: ((env =='dev') ? aksVmSku_dev : aksVmSku_testProd) // (2 cores, 8GB) VS (4 cores and 14GB)
      loadBalancerType: 'InternalLoadBalancer'
      aksNetworkingConfiguration:  {
        subnetId: aksSubnetId
        dnsServiceIP:aksDnsServiceIP
        dockerBridgeCidr:aksDockerBridgeCidr
        serviceCidr:aksServiceCidr
      }
      loadBalancerSubnet: aksSubnetName // aks-subnet is default
      
    }
  }
  dependsOn: [
    ...(!enablePublicAccessWithPerimeter ? [machineLearningPrivateEndpoint] : [])
    azureMLv2Dev
  ]
}
//AKS attach compute PRIVATE cluster, without SSL
resource machineLearningComputeTestProd 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01-preview' = if(ownSSL == 'disabled' && env=='test' || env=='prod') {	
  name: aksName
  parent: amlv2TestProd
  location: location
  properties: {
    computeType: 'AKS'
    computeLocation: location
    description:'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'
    #disable-next-line BCP318
    resourceId: ((env =='dev') ? aksDev.outputs.aksId : aksTestProd.outputs.aksId)  
    properties: {
      agentCount:  ((env =='dev') ? 1 :  3)
      clusterPurpose: ((env =='dev') ? 'DevTest' : 'FastProd') // 'DenseProd' also available
      agentVmSize: ((env =='dev') ? aksVmSku_dev : aksVmSku_testProd) // (2 cores, 8GB) VS (4 cores and 14GB)
      loadBalancerType: 'InternalLoadBalancer'
      aksNetworkingConfiguration:  {
        subnetId: aksSubnetId
        dnsServiceIP:aksDnsServiceIP
        dockerBridgeCidr:aksDockerBridgeCidr
        serviceCidr:aksServiceCidr
      }
      loadBalancerSubnet: aksSubnetName // aks-subnet is default
      
    }
  }
  dependsOn: [
    ...(!enablePublicAccessWithPerimeter ? [machineLearningPrivateEndpoint] : [])
    amlv2TestProd
  ]
}
//CPU Cluster
resource machineLearningCluster001 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01-preview' = if(env =='dev') {
  name: take('p${projectNumber}-m01${locationSuffix}-${env}',16) // p001-m1-weu-prod (16/16...or 24)
  parent: azureMLv2Dev
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    computeType: 'AmlCompute'
    computeLocation: location
    description: 'CPU cluster for batch training models ( or batch scoring with AML pipeline) for ${projectName} in ESML-${env} AI Factory. Defaults: Dev=${amlComputeDefaultVmSize_dev}. TestProd=${amlComputeDefaultVmSize_testProd}'
    disableLocalAuth: true
    properties: {
      vmPriority: 'Dedicated'
      vmSize: ((env =='dev') ? amlComputeDefaultVmSize_dev : amlComputeDefaultVmSize_testProd)
      enableNodePublicIp: false
      isolatedNetwork: false
      osType: 'Linux'
      remoteLoginPortPublicAccess: 'Disabled'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: ((env =='dev') ? amlComputeMaxNodex_dev :  amlComputeMaxNodex_testProd)
        nodeIdleTimeBeforeScaleDown: 'PT120S'
      }
      subnet: {
        id: subnetRef
      }
    }
  }
  dependsOn:[
    machineLearningPrivateEndpoint
    azureMLv2Dev
  ]
}
resource machineLearningCluster001TestProd 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01-preview' = if(env =='test' || env =='prod') {
  name: take('p${projectNumber}-m01${locationSuffix}-${env}',16) // p001-m1-weu-prod (16/16...or 24)
  parent: amlv2TestProd
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    computeType: 'AmlCompute'
    computeLocation: location
    description: 'CPU cluster for batch training models ( or batch scoring with AML pipeline) for ${projectName} in ESML-${env} AI Factory. Defaults: Dev=${amlComputeDefaultVmSize_dev}. TestProd=${amlComputeDefaultVmSize_testProd}'
    disableLocalAuth: true
    properties: {
      vmPriority: 'Dedicated'
      vmSize: ((env =='dev') ? amlComputeDefaultVmSize_dev : amlComputeDefaultVmSize_testProd)
      enableNodePublicIp: false
      isolatedNetwork: false
      osType: 'Linux'
      remoteLoginPortPublicAccess: 'Disabled'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: ((env =='dev') ? amlComputeMaxNodex_dev :  amlComputeMaxNodex_testProd)
        nodeIdleTimeBeforeScaleDown: 'PT120S'
      }
      subnet: {
        id: subnetRef
      }
    }
  }
  dependsOn:[
    machineLearningPrivateEndpoint
    amlv2TestProd
  ]
}

output amlId string = (env=='dev')? azureMLv2Dev.id: amlv2TestProd.id
output amlName string =(env=='dev')? azureMLv2Dev.name: amlv2TestProd.name
#disable-next-line BCP318
output principalId string = (env=='dev')?azureMLv2Dev.identity.principalId:  amlv2TestProd.identity.principalId
