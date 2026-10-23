import { trustedLaunch, windowsGen2Image, windowsPatchSettings } from 'common/vmSecurity.bicep'

@description('default is -001 such as esml-dsvm-username-001 as secret name in keyvault Ex: creating multipe VM -001, -002,-003')
param kvSecretNameSuffix string = '-001'

@secure()
@description('Specifies a secure string used as password new local admin user')
param adminPassword string

@description('Specifies the name of the local admin user')
param adminUsername string

@description('Size of the virtual machine. Must support Generation 2, Trusted Launch and (unless enableEncryptionAtHost is false) encryption at host.')
param vmSize string = 'Standard_D2s_v5'

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

var nicName = '${vmName}-nic-${substring(uniqueString(vmName), 0, 5)}'
var subnetRef = '${vnetId}/subnets/${subnetName}'

@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool = true

@description('default keyvault secret expiration date in inteter, EPOC, seconds after 1970')
param expiration_date_default_2025_01_10_epoch int = 1736467877

@description('default StandardSSD_LRS as demo mode, recommended for production purpose is to upgrade to Premium_LRS. Never HDD (Standard_LRS).')
@allowed([
  'StandardSSD_LRS'
  'StandardSSD_ZRS'
  'Premium_LRS'
  'Premium_ZRS'
])
param osDiskType string = 'StandardSSD_LRS' //'Premium_LRS'
@description('default StandardSSD_LRS as demo mode, recommended is to upgrade to Premium_LRS for productional purpose. Never HDD (Standard_LRS).')
@allowed([
  'StandardSSD_LRS'
  'StandardSSD_ZRS'
  'Premium_LRS'
  'Premium_ZRS'
])
param extraDiskType string = 'StandardSSD_LRS' // StandardSSD_LRS = SSD , 'Premium_LRS'
@description('default is 128GB, change to bigger, 1024, GB if much local data')
param extraDiskSizeGB int = 128 // 1024

@description('Defender for Cloud: encrypt temp disk and caches on the host. Needs the subscription feature Microsoft.Compute/EncryptionAtHost (the bootstrap registers it). Set false to opt out.')
param enableEncryptionAtHost bool = true

@description('true when this VM already exists. An existing VM is never PUT again: image, Trusted Launch and encryption at host cannot change in place (Gen1 DSVMs must be recreated), and the local admin password is not rotated. Only opt-in backup is applied.')
param vmExists bool = false

@description('Opt-in Azure Backup: Recovery Services vault + daily Enhanced policy, protecting this VM.')
param enableVmBackup bool = false

@description('Recovery Services vault used when enableVmBackup is true: created when absent, reused when it exists.')
param backupVaultName string = 'rsv-${vmName}'

resource nInter 'Microsoft.Network/networkInterfaces@2020-06-01' = if (!vmExists) {
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

resource virtualMachine 'Microsoft.Compute/virtualMachines@2024-07-01' = if (!vmExists) {
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
        patchSettings: windowsPatchSettings
      }
    }
    securityProfile: union(trustedLaunch, {
      encryptionAtHost: enableEncryptionAtHost
    })
    storageProfile: {
      // Gen2 + Trusted Launch. The former microsoft-dsvm dsvm-win-2022:winserver-2022 image is Gen1 only.
      imageReference: windowsGen2Image
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

resource extAADLogin 'Microsoft.Compute/virtualMachines/extensions@2024-07-01' = if (!vmExists) {
  parent: virtualMachine
  name: 'AADLoginForWindows'
  location:location
  properties:{
    publisher:'Microsoft.Azure.ActiveDirectory'
    typeHandlerVersion:'1.0'
    type:'AADLoginForWindows'
    autoUpgradeMinorVersion:true
  }
}

module securityExtensions 'vmSecurityExtensions.bicep' = if (!vmExists) {
  name: take('vmSecExt-${vmName}', 64)
  params: {
    vmName: virtualMachine.name
    location: location
    osType: 'Windows'
    tags: tags
  }
  dependsOn: [
    extAADLogin
  ]
}

module backup 'vmBackup.bicep' = if (enableVmBackup) {
  name: take('vmBackup-${vmName}', 64)
  params: {
    vmName: vmName
    location: location
    tags: tags
    vaultName: backupVaultName
  }
  dependsOn: [
    virtualMachine
    securityExtensions
  ]
}

resource automaticShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = if (!vmExists) {
  name: 'shutdown-computevm-${vmName}'
  location: location
  tags: tags
  properties: {
    dailyRecurrence: {
      time: '0330'
    }
    status: 'Enabled'
    targetResourceId: virtualMachine.id
    taskType: 'ComputeVmShutdownTask'
    timeZoneId: 'W. Europe Standard Time'
  }
}

var esmlProjectKVNameUser = 'esml-dsvm-username${kvSecretNameSuffix}'
var esmlProjectKVNamePwd = 'esml-dsvm-password${kvSecretNameSuffix}'

// Written only with a new VM: on an existing VM the password in Key Vault stays the one the VM uses.
resource keyvaultadminUsernameSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = if (!vmExists) {
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
resource keyvaultadminPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = if (!vmExists) {
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

@description('Private VM resource ID. Use this to identify a self-hosted build agent without deriving its name externally.')
output vmResourceId string = resourceId('Microsoft.Compute/virtualMachines', vmName)

@description('Private VM name. Register self-hosted Azure DevOps agents with this exact name.')
output vmName string = vmName
