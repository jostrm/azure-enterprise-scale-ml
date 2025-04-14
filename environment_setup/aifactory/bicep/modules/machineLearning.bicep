@description('Specifies the name of the new machine learning studio resources')
param name string
param uniqueDepl string
param uniqueSalt5char string
param locationSuffix string
param aifactorySuffix string
//@description('Specifies the computer pool name')
//param computePoolName string
@description('Specifies the computer pool name')
param projectName string
@description('Specifies the computer pool name')
param projectNumber string

@description('Specifies the location where the new machine learning studio resource should be deployed')
param location string
@description('ESML dev,test or prod. If DEV then AKS cluster is provisioned with 1 agent otherwise 3')
param env string
//@description('Example: esmldev')
//param aksLeafDomainLabel string

@description('Subnet id, also with vnet in path etc, for AKS')
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
param allowPublicAccessWhenBehindVnet bool = true
@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jåaj

var subnetRef = '${vnetId}/subnets/${subnetName}'

// See Azure VM Sku: https://docs.microsoft.com/en-us/azure/virtual-machines/sizes-general
// Standard DSv2 Family vCPUs in West Europe 

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
param alsoManagedMLStudio bool = false
param managedMLStudioName string = ''
param privateEndpointName2 string = ''

param saName string
param saName2 string = ''
param kvName string
param kvName2 string = ''
param acrName string
param acrRGName string
param appInsightsName string
param ipWhitelist_array array = []
param enablePublicAccessWithPerimeter bool = false
param enableAMLWorkspaceVersion1 bool = true

var aiFactoryNumber = substring(aifactorySuffix,1,3) // -001 to 001
var aml_create_ci=false

var nameManaged = empty(managedMLStudioName)? '${name}-mn':managedMLStudioName

resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: saName
}

resource existingStorageAccount2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if(!empty(saName2)){
  name: saName2
}

resource existingKeyvault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: kvName
}
resource existingKeyvault2 'Microsoft.KeyVault/vaults@2023-07-01' existing = if(!empty(kvName2)){
  name: kvName2
}
resource existingAppInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
  scope: resourceGroup(acrRGName)
}


resource machineLearningStudioManaged 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' = if(alsoManagedMLStudio) {
  name: nameManaged
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  properties: {
    allowRoleAssignmentOnRG: true
    friendlyName: nameManaged
    description: 'Azure ML Studio, managed networking, not using legacy V1 mode'

     // dependent resources
    storageAccount: existingStorageAccount2.id
    keyVault: existingKeyvault2.id
    containerRegistry: existingAcr.id
    applicationInsights: existingAppInsights.id

    // configuration
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false
    provisionNetworkNow: true
    enableDataIsolation: false // tomten
    v1LegacyMode:false

    // network settings
    publicNetworkAccess: enablePublicAccessWithPerimeter? 'Enabled': 'Disabled' // tomten: enablePublicGenAIAccess?'Enabled':'Disabled' -> 'Disabled' 
    allowPublicAccessWhenBehindVnet: enablePublicAccessWithPerimeter? true: allowPublicAccessWhenBehindVnet
    managedNetwork: {
      firewallSku:'Basic' // 'Standard'
      isolationMode:enablePublicAccessWithPerimeter? 'Disabled': 'AllowInternetOutBound' // tomten: enablePublicGenAIAccess? 'AllowInternetOutBound': 'AllowOnlyApprovedOutbound'
    }
    ipAllowlist: ipWhitelist_array
    /*
    networkAcls: {
      defaultAction:'Allow' // enablePublicAccessWithPerimeter? 'Allow':'Deny' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      ipRules: ipRules
    }
    */
  }
  dependsOn:[
    machineLearningStudio
  ]
  
}
module machineLearningPrivateEndpoint2 'machinelearningNetwork.bicep' = {
  name: 'mlNetworking2${uniqueDepl}'
  scope: resourceGroup()
  params: {
    location: location
    tags: tags
    workspaceArmId: machineLearningStudioManaged.id
    subnetId: subnetRef
    machineLearningPleName: privateEndpointName2
    amlPrivateDnsZoneID: amlPrivateDnsZoneID
    notebookPrivateDnsZoneID: notebookPrivateDnsZoneID
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
}

//resource machineLearningStudio 'Microsoft.MachineLearningServices/workspaces@2022-10-01' = {
//resource machineLearningStudio 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = {
resource machineLearningStudio 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' = if(env == 'dev' && enableAMLWorkspaceVersion1) {
  name: name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  //sku: {
  //  name: skuName
  //  tier: skuTier
  //}
  properties: {
    friendlyName: name
    description:  '${projectName}-${env}-${aiFactoryNumber}'

    storageAccount: existingStorageAccount.id
    containerRegistry: existingAcr.id
    keyVault: existingKeyvault.id
    applicationInsights: existingAppInsights.id

    // configuration for workspaces with private link endpoint
    allowRoleAssignmentOnRG: true
    imageBuildCompute: '${name}/p${projectNumber}-m01${locationSuffix}-${env}' //'cluster001'
    allowPublicAccessWhenBehindVnet: true //allowPublicAccessWhenBehindVnet tomten
    publicNetworkAccess: 'Disabled'
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false // tomten
    v1LegacyMode:true // tomten
    //provisionNetworkNow: false // tomten
    enableDataIsolation: false // tomten
    ipAllowlist: ipWhitelist_array
    /*
    networkAcls: {
      defaultAction:'Allow' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      ipRules: ipRules
    }
    */
  }
  dependsOn:[
    aksDev
  ]
}
resource machineLearningStudioTestProd 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview'  = if(env == 'test' || env == 'prod' && enableAMLWorkspaceVersion1) {
  name: name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  //sku: {
  //  name: skuName
  //  tier: skuTier
  //}
  properties: {
    friendlyName: name
    description:  '${projectName}-${env}-${aiFactoryNumber}'

    storageAccount: existingStorageAccount.id
    containerRegistry: existingAcr.id
    keyVault: existingKeyvault.id
    applicationInsights: existingAppInsights.id

    // configuration for workspaces with private link endpoint
    allowRoleAssignmentOnRG: true
    imageBuildCompute: '${name}/p${projectNumber}-m01${locationSuffix}-${env}' //'cluster001'
    allowPublicAccessWhenBehindVnet: true //allowPublicAccessWhenBehindVnet tomten
    publicNetworkAccess: 'Enabled'
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false // tomten
    v1LegacyMode:true // tomten
    //provisionNetworkNow: false // tomten
    enableDataIsolation: false // tomten
    networkAcls: {
      defaultAction:'Allow'
      ipRules: ipRules
    }
  }
  dependsOn:[
    aksTestProd
  ]
}

module machineLearningPrivateEndpoint 'machinelearningNetwork.bicep' = {
  name: 'mlNetworking1${uniqueDepl}'
  scope: resourceGroup()
  params: {
    location: location
    tags: tags
    workspaceArmId: (env=='dev')? machineLearningStudio.id: machineLearningStudioTestProd.id
    subnetId: subnetRef
    machineLearningPleName: privateEndpointName
    amlPrivateDnsZoneID: amlPrivateDnsZoneID
    notebookPrivateDnsZoneID: notebookPrivateDnsZoneID
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
}

var aksName = 'esml${projectNumber}-${locationSuffix}-${env}' // esml001-weu-prod (20/16) VS esml001-weu-prod (16/16)
var nodeResourceGroupName = 'aks-${resourceGroup().name}' // aks-abc-def-esml-project001-weu-dev-003-rg (unique within subscription)

module aksDev 'aksCluster.bicep'  = if(env == 'dev') {
  name: 'AMLAKSDev4${uniqueDepl}'
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
  name: 'AMLAKSTestProd4${uniqueDepl}'
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
resource machineLearningCompute 'Microsoft.MachineLearningServices/workspaces/computes@2022-10-01' = if(ownSSL == 'disabled' && env=='dev') {	
  name: aksName
  parent: machineLearningStudio
  location: location
  properties: {
    computeType: 'AKS'
    computeLocation: location
    description:'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'
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
  dependsOn:[
    machineLearningPrivateEndpoint
    machineLearningStudio
  ]
}
//AKS attach compute PRIVATE cluster, without SSL
resource machineLearningComputeTestProd 'Microsoft.MachineLearningServices/workspaces/computes@2022-10-01' = if(ownSSL == 'disabled' && env=='test' || env=='prod') {	
  name: aksName
  parent: machineLearningStudioTestProd
  location: location
  properties: {
    computeType: 'AKS'
    computeLocation: location
    description:'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'
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
  dependsOn:[
    machineLearningPrivateEndpoint
    machineLearningStudioTestProd
  ]
}
//CPU Cluster
resource machineLearningCluster001 'Microsoft.MachineLearningServices/workspaces/computes@2022-10-01' = if(env =='dev') {
  name: 'p${projectNumber}-m01${locationSuffix}-${env}' // p001-m1-weu-prod (16/16...or 24)
  parent: machineLearningStudio
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
    machineLearningStudio
  ]
}
resource machineLearningCluster001TestProd 'Microsoft.MachineLearningServices/workspaces/computes@2022-10-01' = if(env =='test' || env =='prod') {
  name: 'p${projectNumber}-m01${locationSuffix}-${env}' // p001-m1-weu-prod (16/16...or 24)
  parent: machineLearningStudioTestProd
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
    machineLearningStudioTestProd
  ]
}

//Compute instance
resource machineLearningComputeInstance001 'Microsoft.MachineLearningServices/workspaces/computes@2022-10-01' = if(aml_create_ci==true) {
  name: 'p${projectNumber}-m01-${uniqueSalt5char}-${env}-ci01' // p001-m01-12345-prod-ci01 (24/24)(The name needs to be unique within an Azure region)
  parent: machineLearningStudio
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    computeType: 'ComputeInstance'
    computeLocation: location
    description: ' Azure Compute Instance (CI),Default and shared, to power notebooks, for ${projectName} in ESML-${env} AI Factory environment. Dev=${ciVmSku_dev}. TestProd=${ciVmSku_testProd}'
    disableLocalAuth: true
    properties: {
      applicationSharingPolicy: 'Shared'//'Personal'
      computeInstanceAuthorizationType: 'personal'
      enableNodePublicIp: false
      sshSettings: {
        sshPublicAccess: 'Disabled'
      }
      subnet: {
        id: subnetRef
      }
      vmSize:  ((env =='dev') ? ciVmSku_dev : ciVmSku_testProd)
    }
  }
  dependsOn:[
    machineLearningPrivateEndpoint
    machineLearningCluster001
    machineLearningCompute
  ]
}

output amlId string = (env=='dev')? machineLearningStudio.id: machineLearningStudioTestProd.id
output amlName string =(env=='dev')? machineLearningStudio.name: machineLearningStudioTestProd.name
output principalId string = (env=='dev')?machineLearningStudio.identity.principalId:  machineLearningStudioTestProd.identity.principalId

// ###############  AML networking - custom networking ###############
output dnsConfig array = [
  {
    name: privateEndpointName //pendAml.name
    type: 'amlworkspace'
  }
]
