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

@description('Subnet id')
param aksSubnetId string
@description('Specifies the skuname of the machine learning studio')
param skuName string

@description('Specifies the sku tier of the machine learning studio')
param skuTier string

@description('Specifies the storageaccount id used for the machine learning studio')
param storageAccount string

@description('Specifies the container registry id used for the machine learning studio')
param containerRegistry string

@description('Specifies the keyvault id used for the machine learning studio')
param keyVault string

@description('Specifies the application insights id used for the machine learning studio')
param applicationInsights string

//@description('Specifies the aks id used for the machine learning studio')
//param aksClusterId string

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
param kubernetesVersionAndOrchestrator string = '1.23.3'

@description('AKS Kubernetes version and AgentPool orchestrator version')
param allowPublicAccessWhenBehindVnet bool = false

@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jåaj

var subnetRef = '${vnetId}/subnets/${subnetName}'

// See Azure VM Sku: https://docs.microsoft.com/en-us/azure/virtual-machines/sizes-general
// Standard DSv2 Family vCPUs in West Europe 

// AKS: NB! Standard_D12 is not allowed in WE for agentpool   [standard_a4_v2]
param aks_dev_defaults array = [
  'Standard_A4m_v2' // 4cores, 32GB, 40GB storage (quota:100)
  'Standard_D3_v2' // 4 cores, 14GB RAM, 200GB storage
] 

param aks_testProd_defaults array = [
  'Standard_DS13-2_v2' // 8 cores, 14GB, 112GB storage
  'Standard_A8m_v2' // 8 cores, 64GB RAM, 80GB storage (quota:100)
]

param aml_dev_defaults array = [
  'Standard_DS3_v2' // 	4 cores, 14GB ram, 28GB storage = 0.27$ [Classical ML model training on small datasets]
  'Standard_F8s_v2' //  (8,16,64) 0.39$
  'Standard_DS12_v2' // 4 cores, 28GB RAM, 56GB storage = 0.38 [Data manipulation and training on medium-sized datasets (1-10GB)
]

param aml_testProd_defaults array = [
  'Standard_D13_v2' // 	(8 cores, 56GB, 400GB storage) = 0.76$ [Data manipulation and training on large datasets (>10 GB)]
  'Standard_D4_v2' // (8 cores, 28GB RAM, 400GB storage) = 0.54$
  'Standard_F16s_v2' //  (16 cores, 32GB RAM, 128GB storage) = 0.78$
]

param ci_dev_defaults array = [
  'Standard_DS11_v2' // 2 cores, 14GB RAM, 28GB storage
]
param ci_devTest_defaults array = [
  'Standard_D11_v2'
]

@description('DEV default VM size for the default compute cluster: STANDARD_D3')
param amlComputeDefaultVmSize_dev string = aml_dev_defaults[0] // 'Standard_D3_v2' //// STANDARD_D4(4,16b ram) Standard_D14 (16 cores,112 ram) 
@description('TestProd default VM size for the default compute cluster: STANDARD_D4')
param amlComputeDefaultVmSize_testProd string = aml_testProd_defaults[1] // 'STANDARD_D4' //// STANDARD_D4(4,16b ram) Standard_D14 (16 cores,112 ram) 

@description('DEV default  VM size for the default AKS cluster:Standard_D12. More: Standard_D3_v2(4,14)')
param aksVmSku_dev string = aks_dev_defaults[0]
@description('TestProd default  VM size for the default AKS cluster:Standard_D12(4,28,200GB)')
param aksVmSku_testProd string = aks_testProd_defaults[0] //'Standard_DS13-2_v2' ////Standard_D12 (4,28,200GB) 'Standard_DS13-2_v2' // Standard_D14 (16 cores,112 ram)

@description('DEV default VM size for the default Compute Instance cluster:Standard_D4_v3(4,16,100)')
param ciVmSku_dev string = ci_dev_defaults[0] 
@description('TestProd default VM size for the default Compute Instance cluster:Standard_D4_v3. More: Standard_D14 (16 cores,112 ram)')
param ciVmSku_testProd string = ci_devTest_defaults[0]

var aiFactoryNumber = substring(aifactorySuffix,1,3) // -001 to 001

resource machineLearningStudio 'Microsoft.MachineLearningServices/workspaces@2021-04-01' = {
  name: name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    friendlyName: '${projectName}-${env}-${aiFactoryNumber}'
    description: 'Azure ML workspace for ${projectName} in ESML-${env} environment. In AI Factory(${aiFactoryNumber}), in ${location}'

    storageAccount: storageAccount
    containerRegistry: containerRegistry
    keyVault: keyVault
    applicationInsights: applicationInsights
    
    // configuration for workspaces with private link endpoint
    imageBuildCompute: 'cluster001'
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet // todo later..test set to TRUE?

    // If sensitive data
    hbiWorkspace:false
  }
}
module machineLearningPrivateEndpoint 'machinelearningNetwork.bicep' = {
  name: 'machineLearningNetworking${uniqueDepl}'
  scope: resourceGroup()
  params: {
    location: location
    tags: tags
    workspaceArmId: machineLearningStudio.id
    subnetId: subnetRef
    machineLearningPleName: privateEndpointName
    amlPrivateDnsZoneID: amlPrivateDnsZoneID
    notebookPrivateDnsZoneID: notebookPrivateDnsZoneID
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
}

var aksName = 'esml${projectNumber}-${locationSuffix}-${env}' // esml-prj001-weu-prod (20/16) VS esml001-weu-prod (16/16)
var nodeResourceGroupName = 'aks-${resourceGroup().name}' // aks-abc-def-esml-project001-weu-dev-003-rg (unique within subscription)

module aksDev 'aksCluster.bicep'  = if(env == 'dev'){
  //scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLAKSDev4${uniqueDepl}'
  params: {
    name: aksName //'aks-${projectName}-${locationSuffix}-${env}${prjResourceSuffix}'
    tags: tags
    location: location
    kubernetesVersion: kubernetesVersionAndOrchestrator // az aks get-versions --location westeurope --output table    // in Westeurope '1.21.2'  is not allowed/supported
    dnsPrefix: '${aksName}-dns'
    enableRbac: true
    nodeResourceGroup: nodeResourceGroupName // 'esml-${replace(projectName, 'prj', 'project')}-aksnode-${env}-rg'
    agentPoolProfiles: [
      {
        name: toLower('agentpool')
        count: 1
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

  dependsOn: [
    machineLearningPrivateEndpoint
  ]
}

module aksTestProd 'aksCluster.bicep'  = if(env == 'test' || env == 'prod'){
  //scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLAKSTestProd4${uniqueDepl}'
  params: {
    name: aksName // 'aks-${projectName}-${locationSuffix}-${env}${prjResourceSuffix}'
    tags: tags
    location: location
    kubernetesVersion: kubernetesVersionAndOrchestrator // az aks get-versions --location westeurope --output table  1.22.6 and 1.23.3(preview) // in Westeurope '1.21.2'  is not allowed/supported
    dnsPrefix: '${aksName}-dns' // 'aks-${projectName}-${locationSuffix}-${env}${prjResourceSuffix}'
    enableRbac: true
    nodeResourceGroup: nodeResourceGroupName //'esml-${replace(projectName, 'prj', 'project')}-aksnode-${env}-rg'
    agentPoolProfiles: [
      {
        name: 'agentpool'
        count: 3
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
  dependsOn: [
    machineLearningPrivateEndpoint
  ]
}

//AKS attach compute
resource machineLearningCompute 'Microsoft.MachineLearningServices/workspaces/computes@2021-07-01' = {
  name: '${machineLearningStudio.name}/${aksName}'
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

      aksNetworkingConfiguration:  {
        subnetId: aksSubnetId
      }
    }
  }
  dependsOn:[
    machineLearningPrivateEndpoint
  ]
}

/* jostrm-DEBUG: testa ta bort detta så länge..verkar "tima out" - An error occurred while sending the request. */

//CI

resource machineLearningComputeInstance001 'Microsoft.MachineLearningServices/workspaces/computes@2021-07-01' = {
  name: '${machineLearningStudio.name}/p${projectNumber}-m01-${uniqueSalt5char}-${env}-ci01' // p001-m01-12345-prod-ci01 (24/24)(The name needs to be unique within an Azure region)
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    computeType: 'ComputeInstance'
    computeLocation: location
    description: ' Azure Compute Instance (CI),Default and shared, to power notebooks, for ${projectName} in ESML-${env} AI Factory environment. Defaults: Dev=${ciVmSku_dev}. TestProd=${ciVmSku_testProd}'
    disableLocalAuth: true
    properties: {
      applicationSharingPolicy: 'Shared'//'Personal'
      computeInstanceAuthorizationType: 'personal'
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
  ]
}
      /*
      sslConfiguration: { // ssl.cert must be specified if status is Enabled +AKS
        leafDomainLabel:aksLeafDomainLabel
        status:'Enabled'
        overwriteExistingDomain:true
        cert:''
        cname:''
        key:''
      }
      */

//CPU Cluster
resource machineLearningCluster001 'Microsoft.MachineLearningServices/workspaces/computes@2021-07-01' = {
  name: '${machineLearningStudio.name}/p${projectNumber}-m01${locationSuffix}-${env}' // p001-m1-weu-prod (16/16...or 24)
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
        maxNodeCount: 3
        nodeIdleTimeBeforeScaleDown: 'PT120S'
      }
      subnet: {
        id: subnetRef
      }
    }
  }
  dependsOn:[
    machineLearningPrivateEndpoint
  ]
}

 /*jostrm-DEBUG */

output amlId string = machineLearningStudio.id
output amlName string = machineLearningStudio.name
output principalId string = machineLearningStudio.identity.principalId

output dnsConfig array = [
  {
    name: privateEndpointName //pendAml.name
    type: 'amlworkspace'
  }
]
