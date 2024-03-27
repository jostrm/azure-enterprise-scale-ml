// ########### COMMON PARAMS
@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string
@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string
@description('AI Factory suffix. If you have multiple instances, -001')
param aifactorySuffixRG string
@description('Specifies the tags2 that should be applied to newly created resources')
param tags object
@description('Deployment location.')
param location string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string

// AKS cross-region
param locationAks string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffixAks string
param subscriptionIdAks string

@description('-001,-002, etc')
param prjResourceSuffix string  // sdf
@description('Resource group where your vNet resides')
param commonResourceSuffix string // sdf
@description('Specifies the virtual network name')
param vnetNameBase string = 'vnt-esmlcmn'

var projectName = 'prj${projectNumber}'
var subscriptionIdDevTestProd = subscription().subscriptionId
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg' // esml-project001-weu-dev-002-rg
var commonResourceGroup = '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' // change this to correct rg

var vnetNameFull = '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetId = '${subscription().id}/resourceGroups/${commonResourceGroup}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}'
var uniqueDepl = '${projectName}${locationSuffix}${env}${aifactorySuffixRG}'

// AKS cross-region
var subscriptionIdDevTestProd_AKS = subscriptionIdAks // TODO-AKS-Crossregion : change to correct subscription
var targetResourceGroup_AKS = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffixAks}-${env}${aifactorySuffixRG}-rg' // esml-project001-weu-dev-002-rg
var commonResourceGroup_AKS = '${commonRGNamePrefix}esml-common-${locationSuffixAks}-${env}${aifactorySuffixRG}' // change this to correct rg

var vnetNameFull_AKS = '${vnetNameBase}-${locationSuffixAks}-${env}${commonResourceSuffix}'
var vnetId_AKS = '${subscriptionIdDevTestProd_AKS}/resourceGroups/${commonResourceGroup_AKS}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull_AKS}'
var uniqueDepl_AKS = '${projectName}${locationSuffixAks}${env}${aifactorySuffixRG}'
resource projectResourceGroupAKS 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: targetResourceGroup_AKS
  scope:subscription(subscriptionIdDevTestProd_AKS)
}

// AKS cross-region END

resource projectResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: targetResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

// ########### COMMON PARAMETERS end

// ############## AKS PARAMS [LTS]
//  1.29.0, 1.28.5, 1.28.3, [1.27.9], 1.27.7, 1.26.12, 1.26.10.
param kubernetesVersionAndOrchestrator string = '1.27.9' // 2024-03-14 LTS Earlier: (1.27.3 | 2024-01-25 to 2024-03-14) az aks get-versions --location westeurope --output table). Supported >='1.23.5'
@description('DEV default  VM size for the default AKS cluster:Standard_D12. More: Standard_D3_v2(4,14)')
param aksVmSku_dev string// = aks_dev_defaults[0]
@description('DEV default  VM size for the default AKS cluster:Standard_D12. More: Standard_D3_v2(4,14)')
param aksVmSku_testProd string// = aks_testProd_defaults[0]


@description('EMSL will use default subnetID, built on projectname example: ork/virtualNetworks/vnetNameFull/subnets/snt-prj003-aks')
param overrideSubnetId string = ''
@description('Keep it short. 1 char, since max 16 chars in name')
param aksSuffix string = ''  // sdf
// ################### PARAMS

// ################# AKS VARIABLES
var aksSubnetName  = 'snt-prj${projectNumber}-aks'
var aksSubnetId = '${vnetId_AKS}/subnets/${aksSubnetName}' // ${subscriptions_subscriptionId}/resourceGroups/${commonResourceGroup}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}/subnets/snt-prj003-aks
var activeAksSubnetId = overrideSubnetId == ''? aksSubnetId: overrideSubnetId
var aksName = 'esml${projectNumber}-${locationSuffixAks}-${env}${aksSuffix}' // esml001-weu-prod (20/16) VS esml001-weu-prod (16/16)
var nodeResourceGroupName = 'aks${aksSuffix}-${targetResourceGroup_AKS}' // aks-abc-def-esml-project001-weu-dev-003-rg (unique within subscription)

module aksDev '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/aksCluster.bicep'  = if(env == 'dev'){
  scope: resourceGroup(subscriptionIdDevTestProd_AKS,projectResourceGroupAKS)
  name: 'AMLAKSDev4${uniqueDepl_AKS}'
  params: {
    name: aksName //'aks-{projectNumber}-${locationSuffix}-${env}${prjResourceSuffix}'
    tags: tags
    location: locationAks
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
        vnetSubnetID: activeAksSubnetId
        type: 'VirtualMachineScaleSets'
        maxPods: 30 //110  total maxPods(maxPods per node * node count), the total maxPods(10 * 1) should be larger than 30.
        orchestratorVersion: kubernetesVersionAndOrchestrator // in Westeurope '1.21.2'  is not allowed/supported
        osDiskSizeGB: 128
      }
    ]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module aksTestProd '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/aksCluster.bicep'  = if(env == 'test' || env == 'prod'){
  scope: resourceGroup(subscriptionIdDevTestProd_AKS,projectResourceGroupAKS)
  name: 'AMLAKSTestProd4${uniqueDepl_AKS}'
  params: {
    name: aksName //'aks-{projectNumber}-${locationSuffix}-${env}${prjResourceSuffix}'
    tags: tags
    location: locationAks
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
        vnetSubnetID: activeAksSubnetId
        type: 'VirtualMachineScaleSets'
        maxPods: 30 // maxPods: 110
        orchestratorVersion: kubernetesVersionAndOrchestrator // in Westeurope '1.21.2'  is not allowed/supported
      }
    ]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

param machineLearningStudioName string = 'aml-prj${projectNumber}-${locationSuffix}-${env}${prjResourceSuffix}' // aml-prj003-weu-dev-002
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

//AKS attach compute PRIVATE cluster, without SSL
resource machineLearningCompute 'Microsoft.MachineLearningServices/workspaces/computes@2021-07-01' = if(ownSSL == 'disabled') {
  name: '${machineLearningStudioName}/${aksName}'
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
        subnetId: activeAksSubnetId
        dnsServiceIP:aksDnsServiceIP
        dockerBridgeCidr:aksDockerBridgeCidr
        serviceCidr:aksServiceCidr
      }
      loadBalancerSubnet:aksSubnetName // aks-subnet is default
      
    }
  }
}

//AKS attach compute, PRIVATE cluster, with SSL
//Error: he resource 'Microsoft.MachineLearningServices/workspaces/aml-prj003-weu-dev-002/computes/esml003-weu-dev4' at line '181' and column '9' is defined multiple times in a template. 

/*
resource machineLearningComputeSSL 'Microsoft.MachineLearningServices/workspaces/computes@2021-07-01' = if(ownSSL == 'enabled') {
  name: '${machineLearningStudioName}/${aksName}'
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
        subnetId: activeAksSubnetId
        dnsServiceIP:aksDnsServiceIP
        dockerBridgeCidr:aksDockerBridgeCidr
        serviceCidr:aksServiceCidr
      }
      loadBalancerSubnet: 'aks-subnet' // aks-subnet is default
      sslConfiguration:{
        cert:aksCert
        cname:aksCname
        key:aksCertKey
        overwriteExistingDomain:aksSSLOverwriteExistingDomain
        status:aksSSLstatus
      }
      
    }
  }

}
*/
