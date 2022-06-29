@description('Specifies the name of the NSG, network security group')
param name string

@description('Specifies the location where the  network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the network security group')
param tags object

@description('To lock INBOUND rule to only allow RDP anbd SSH ports from Azure Bastion  via private IP')
param bastionIpRange string

resource cmnNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      { //!
        name: 'AML_CI_44224'
        properties: {
          description: 'Required for Azure Machine Learning'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '44224'
          sourceAddressPrefix: 'AzureMachineLearning'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1050
          direction: 'Inbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: []
        }
      }
      { //!
        name: 'AML_Port_29876-29877'
        properties: {
            description: 'Required for Azure Machine Learning batch compute nodes'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '29876-29877'
            sourceAddressPrefix: 'BatchNodeManagement'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 1040
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Bastion_GetSessionInformation'
        properties: {
            description: 'Bastion will reach to the VM (DSVM / jump server) over private IP. RDP/SSH ports 3389/22. NB! Change the IP range if not working'
            protocol: '*'
            sourcePortRange: '*'
            sourceAddressPrefix: bastionIpRange
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 1300
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: [
              '22'
              '3389'
            ]
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      // --- Outbound --- 
      {
        name: 'AzureDevOps_Allow_1'
        properties: {
            description: 'Required for communication to Azure Devops. Needed to checkin code'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: '*'
            access: 'Allow'
            priority: 100
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: [
              '13.107.6.0/24'
              '13.107.9.0/24'
              '13.107.42.0/24'
              '13.107.43.0/24'
            ]
        }
      }
      {
        name: 'AADLoginForWindows_Allow3services'
        properties: {
            description: 'To enable Azure AD authentication for Windows VMs.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 110
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: [] // https://enterpriseregistration.windows.net - For device registration. http://169.254.169.254 - Azure Instance Metadata Service endpoint. 
            // https://login.microsoftonline.com - For authentication flows.  https://pas.windows.net - For Azure RBAC flows.
        }
      }
      {
        name: 'AADLoginForWindows_AllowServiceMeta'
        properties: {
            description: 'To enable Azure AD authentication for Windows VMs.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '80'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: '169.254.169.254'
            access: 'Allow'
            priority: 120
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: [] // https://enterpriseregistration.windows.net - For device registration. http://169.254.169.254 - Azure Instance Metadata Service endpoint. 
            // https://login.microsoftonline.com - For authentication flows.  https://pas.windows.net - For Azure RBAC flows.
        }
      }
      {// !! 
        name: 'AzureActiveDirectory'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          access: 'Allow'
          priority: 130
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureMachineLearningOutbound'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureMachineLearning'
          access: 'Allow'
          priority: 140
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureResourceManager'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureResourceManager'
          access: 'Allow'
          priority: 150
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureStorageAccount'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage.${location}'
          access: 'Allow'
          priority: 160
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureFrontDoor'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureFrontDoor.FrontEnd'
          access: 'Allow'
          priority: 170
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureContainerRegistry'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureContainerRegistry.${location}'
          access: 'Allow'
          priority: 180
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'MicrosoftContainerRegistry'
        properties: {
          description: 'AML !!'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'MicrosoftContainerRegistry'
          access: 'Allow'
          priority: 200
          direction: 'Outbound'
        }
      }
    ]
  }
}

output nsgId string = cmnNsg.id
