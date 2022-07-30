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
param location string = resourceGroup().location

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

var nicName = '${vmName}-nic-${substring(uniqueString(vmName), 0, 5)}'
var subnetRef = '${vnetId}/subnets/${subnetName}'

@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool = true

@description('default keyvault secret expiration date in inteter, EPOC, seconds after 1970')
param expiration_date_default_2025_01_10_epoch int = 1736467877

@description('default StandardSSD_LRS as demo mode, recommended for production purpose is to upgrade to Premium_LRS ')
param osDiskType string = 'StandardSSD_LRS' //'Premium_LRS'
@description('default StandardSSD_LRS as demo mode, recommended is to upgrade to Premium_LRS for productional purpose ')
param extraDiskType string = 'StandardSSD_LRS' // 'Standard_LRS' = HDD , StandardSSD_LRS = SSD , 'Premium_LRS'
@description('default is 128GB, change to bigger, 1024, GB if much local data')
param extraDiskSizeGB int = 128 // 1024

resource nInter 'Microsoft.Network/networkInterfaces@2020-06-01' = {
  name: nicName
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: subnetRef
          }
        }
      }
    ]
  }
}

resource virtualMachine 'Microsoft.Compute/virtualMachines@2020-12-01' = {
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
          storageAccountType: osDiskType
        }
      }
      dataDisks: [
        {
          diskSizeGB: extraDiskSizeGB
          managedDisk: {
            storageAccountType: extraDiskType
          }
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

resource extAADLogin 'Microsoft.Compute/virtualMachines/extensions@2020-12-01' = {
  name: '${vmName}/AADLoginForWindows'
  location:location
  properties:{
    publisher:'Microsoft.Azure.ActiveDirectory'
    typeHandlerVersion:'1.0'
    type:'AADLoginForWindows'
    autoUpgradeMinorVersion:true
  }
  dependsOn:[
    virtualMachine //extDCforAADLogin
  ]
}


resource automaticShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${virtualMachine.name}'
  location: location
  tags: tags
  properties: {
    dailyRecurrence: {
      time: '2300'
    }
    status: 'Enabled'
    targetResourceId: virtualMachine.id
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
