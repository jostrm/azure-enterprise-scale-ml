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

@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool

var subnetRef = '${vnetId}/subnets/${subnetName}'
var pipNicName = '${vmName}-nic-${substring(uniqueString(vmName), 0, 5)}'

resource pip 'Microsoft.Network/publicIPAddresses@2021-05-01' = {
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

resource nInter 'Microsoft.Network/networkInterfaces@2020-06-01' = {
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

resource vmAvd 'Microsoft.Compute/virtualMachines@2021-11-01' = {
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
      computerName: substring(vmName,0,14)
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

// REF1:  https://techcommunity.microsoft.com/t5/azure-virtual-desktop/avd-bicep-deployment-with-add-joined/m-p/3033470
// REF2: https://tighetec.co.uk/2021/07/07/deploy-azure-virtual-desktop-with-project-bicep/
// REF 3: 
//Extentions - MicrosoftMonitoringAgent AADLoginForWindows, AzurePolicyforWindows,MDE.Windows, MicrosoftMonitoringAgent, MDE.Windows
//AzureNetworkWatcherExtension

var hostPoolName = 'esmlHostPool001'
var hostPoolToken = '' // New-AzWvdRegistrationInfo -ResourceGroupName <resourcegroupname> -HostPoolName <hostpoolname> -ExpirationTime $((get-date).ToUniversalTime().AddHours(2).ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ'))
var hostPoolType = 'Personal'
var loadbalancerType = 'BreadthFirst'
var artifactsLocation = 'https://wvdportalstorageblob.blob.${environment().suffixes.storage}/galleryartifacts/Configuration_11-22-2021.zip'

resource extDCforAADLogin 'Microsoft.Compute/virtualMachines/extensions@2021-11-01' = {
  name: '${vmName}/extDCforAADLogin' 
  location: location
  properties:{
    publisher:'Microsoft.Powershell'
    type:'DSC' // Desired State Configuration
    typeHandlerVersion:'2.73'
    autoUpgradeMinorVersion:true
    settings:{
      modulesUrl:artifactsLocation
      configurationFunction:'Configuration.ps1\\AddSessionHost' // Azure virtual desktop sessionhost
      properties: {
        HostPoolName:hostPoolName
        RegistrationInfoToken: hostPoolToken
        AadJoin:true
      }
    }
  }
  dependsOn:[
    vmAvd
  ]
}

resource extAADLogin 'Microsoft.Compute/virtualMachines/extensions@2021-11-01' = {
  name: '${vmName}/AADLoginForWindows'
  location:location
  properties:{
    publisher:'Microsoft.Azure.ActiveDirectory'
    type:'AADLoginForWindows'
    typeHandlerVersion:'1.0'
    autoUpgradeMinorVersion:true
  }
  dependsOn:[
    vmAvd
  ]
}

resource hostPool 'Microsoft.DesktopVirtualization/hostPools@2021-07-12' = {
  name: hostPoolName
  location:location
  properties: {
    hostPoolType: hostPoolType
    loadBalancerType: loadbalancerType
    preferredAppGroupType: 'Desktop'
    customRdpProperty:''
  }
}

resource automaticShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${vmAvd.name}'
  location: location
  tags: tags
  properties: {
    dailyRecurrence: {
      time: '2300'
    }
    status: 'Enabled'
    targetResourceId: vmAvd.id
    taskType: 'ComputeVmShutdownTask'
    timeZoneId: 'W. Europe Standard Time'
  }
}

resource keyvaultadminPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/virtualMachineAdminPassword'
  properties: {
    value: adminPassword
  }
}

resource keyvaultadminUsernameSecret 'Microsoft.KeyVault/vaults/secrets@2019-09-01' = {
  name: '${keyvaultName}/virtualMachineAdminUsername'
  properties: {
    value: adminUsername
  }
}

output hostname string = pip.properties.dnsSettings.fqdn
