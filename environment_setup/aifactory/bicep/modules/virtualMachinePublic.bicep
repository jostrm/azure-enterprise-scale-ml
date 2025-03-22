@description('default is -001 such as esml-dsvm-username-001 as secret name in keyvault Ex: creating multipe VM -001, -002,-003')
param kvSecretNameSuffix string = '-001'
@secure()
@description('Specifies a secure string used as password new local admin user')
param adminPassword string

@description('Specifies the name of the local admin user')
param adminUsername string

@description('Size of the virtual machine.')
param vmSize string = 'Standard_D2_v3'

@description('location for all resources')
param location string

@description('Specifies the name of the virtual machine')
param vmName string

@description('Specifies the subnet that the virtual machine should be connected to')
param subnetName string

@description('Specift the virtual network id used for network interface')
param vnetId string

@description('The tags that should be applied on virtual machine resources')
param tags object

@description('(Required) speficies the keyvault used to save local admin credentials')
param keyvaultName string
@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool = true

@description('default keyvault secret expiration date in inteter, EPOC, seconds after 1970')
param expiration_date_default_2025_01_10_epoch int = 1736467877

// Two different names are generated because of the conditional resources.
// Without this we get a duplicate resource error

var subnetRef = '${vnetId}/subnets/${subnetName}'

// --- Public IP VM ---
var pipNicName = '${vmName}-nic-${substring(uniqueString(vmName), 0, 5)}'

// Can be good for DEBUG-purpose. Need to whitelist your client IP in NSG if connecting to this in that case.
resource pip 'Microsoft.Network/publicIPAddresses@2020-08-01' = {
  name: 'ip-${vmName}'
  location: location
  sku:{
    name:'Standard'
    tier:'Regional'
  }
  tags: tags
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: {
      domainNameLabel: '${vmName}-pub'
    }
  }
}

resource nInter 'Microsoft.Network/networkInterfaces@2020-08-01' = {
  name: pipNicName
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: pip.id
          }
          subnet: {
            id: subnetRef
          }
        }
      }
    ]
  }
}

resource virtualMachineWithPublicIp 'Microsoft.Compute/virtualMachines@2020-12-01' = {
  name: vmName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    licenseType:((hybridBenefit == true) ?   'Windows_Server' :  'None') // HB='Windows_Server'  & "pay as you go"='None'
    osProfile: {
      computerName: substring(vmName,0,14) // No more than 15 chars are allowed for this field
      adminUsername: adminUsername
      adminPassword: adminPassword
      windowsConfiguration: {
        enableAutomaticUpdates: true
        provisionVMAgent: true
        patchSettings: {
          enableHotpatching: false
          patchMode: 'AutomaticByOS'
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'microsoft-dsvm'
        offer: 'dsvm-win-2019'
        sku: 'server-2019'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB:256
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
      }
      dataDisks: [
        {
          diskSizeGB: 1024
          lun: 0
          createOption: 'Empty'
        }
      ]
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nInter.id
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
    
  }
}
//Extentions - MicrosoftMonitoringAgent AADLoginForWindows, AzurePolicyforWindows,MDE.Windows, MicrosoftMonitoringAgent, MDE.Windows
//AzureNetworkWatcherExtension

resource extAADLogin 'Microsoft.Compute/virtualMachines/extensions@2020-06-01' = {
  name: '${vmName}/AADLoginForWindows'
  location:location
  properties:{
    publisher:'Microsoft.Azure.ActiveDirectory'
    type:'AADLoginForWindows' // NB: If "type:" is missing: Error: The value of parameter type is invalid.  "target": "type"
    typeHandlerVersion:'1.0'
    autoUpgradeMinorVersion:true
  }
  dependsOn:[
    virtualMachineWithPublicIp //extDCforAADLogin
  ]
}

resource automaticShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${virtualMachineWithPublicIp.name}'
  location: location
  tags: tags
  properties: {
    dailyRecurrence: {
      time: '2300'
    }
    status: 'Enabled'
    targetResourceId: virtualMachineWithPublicIp.id
    taskType: 'ComputeVmShutdownTask'
    timeZoneId: 'W. Europe Standard Time'
  }
}

var esmlProjectKVNameUser = 'esml-dsvm-username${kvSecretNameSuffix}'
var esmlProjectKVNamePwd = 'esml-dsvm-password${kvSecretNameSuffix}'

resource keyvaultadminUsernameSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlProjectKVNameUser}'
  properties: {
    value: adminUsername
    contentType: 'ESML generated local admin'
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}
resource keyvaultadminPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/${esmlProjectKVNamePwd}'
  properties: {
    contentType: 'ESML generated local admin password for username ${adminUsername} on VM'
    value: adminPassword
    attributes: {
      enabled: true
      exp:expiration_date_default_2025_01_10_epoch
    }
  }
}


output hostname string = pip.properties.dnsSettings.fqdn
