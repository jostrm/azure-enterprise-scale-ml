@description('Specifies the name of the NSG, network security group')
param name string

@description('Specifies the location where the  network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the network security group')
param tags object

@description('To lock INBOUND rule to only allow RDP anbd SSH ports from Azure Bastion  via private IP')
param bastionIpRange string
param enableFlowLogs bool = true
param storageAccountId string = ''
param networkWatcherName string = 'NetworkWatcher_${location}'
param networkWatcherResourceGroup string = 'NetworkWatcherRG'
param flowLogRetentionDays int = 30

// TODO: outbound connection to ports 443, 445 for storage service tag

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
          priority: 4200
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
            priority: 4100
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
            protocol: 'Tcp'
            sourcePortRange: '*'
            sourceAddressPrefix: bastionIpRange
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 4300
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
      // DEBUG RULE - UNCOMMENT ONLY FOR TROUBLESHOOTING
      // WARNING: This allows ALL inbound traffic - use only temporarily!
      // To enable: Remove the // comments from the rule below
      /*
      {
        name: 'DEBUG_AllowAllInbound_TEMPORARY'
        properties: {
            description: 'DEBUG ONLY: Allow all inbound for troubleshooting AI Foundry agents. REMOVE AFTER DEBUGGING!'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 4000
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      */
       {
        name: 'Allow_VNet_Inbound'
        properties: {
            description: 'Allow traffic from other subnets in same VNet'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 3900
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'DenyAllInboundExceptExplicit'
        properties: {
            description: 'Deny all other inbound traffic not explicitly allowed above'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: '*'
            access: 'Deny'
            priority: 65000
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
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
            sourceAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 4000
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
        name: 'AzureActiveDirectoryDomainServices_Allow'
        properties: {
            description: 'Required for Azure Active Directory Domain Services communication'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: 'AzureActiveDirectoryDomainServices'
            access: 'Allow'
            priority: 4050
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
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
            priority: 4100
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
            priority: 4200
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
          description: 'AML - Azure AD authentication (HTTPS only)'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          access: 'Allow'
          priority: 4300
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
          priority: 4400
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
          priority: 4500
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'AzureStorageAccount'
        properties: {
          description: 'AML - Azure Storage (HTTPS and SMB)'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRanges: [
            '443'
            '445'
          ]
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage.${location}'
          access: 'Allow'
          priority: 4600
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
          priority: 4700
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
          priority: 4800
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
          priority: 4900
          direction: 'Outbound'
        }
      }
      {
        name: 'AKS_private_loadbalancer_call_from_DSVM_in_vNet'
        properties: {
            description: 'Required for communication from private DSVM to call private AKS cluster endpoints. Needed for Azure ML inferencing.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '80'
            sourceAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 5000
            direction: 'Outbound'
            destinationAddressPrefix: 'VirtualNetwork'
        }
      }
      {
        name: 'AzureMachineLearning_2023_sdkv2_1'
        properties: {
            description: 'Required for 2023 Mars update, to support Azure ML SDK v2'
            protocol: 'Udp'
            sourcePortRange: '*'
            destinationPortRange: '5831'
            sourceAddressPrefix: '*'
            access: 'Allow'
            priority: 5100
            direction: 'Outbound'
            destinationAddressPrefix: 'AzureMachineLearning'
        }
      }
      {
        name: 'AzureMachineLearning_2023_sdkv2_2'
        properties: {
            description: 'Required for 2023 Mars update, to support Azure ML SDK v2'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '5831'
            sourceAddressPrefix: '*'
            access: 'Allow'
            priority: 5300
            direction: 'Outbound'
            destinationAddressPrefix: 'BatchNodeManagement.${location}'
        }
      }
      {
        name: 'AzureMachineLearning_2023_sdkv2_3'
        properties: {
            description: 'Required for 2023 Mars update, to support Azure ML SDK v2'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRanges: [
              '8787'
              '18881'
            ]
            sourceAddressPrefix: '*'
            access: 'Allow'
            priority: 5200
            direction: 'Outbound'
            destinationAddressPrefix: 'AzureMachineLearning'
        }
      }
      {// !! Data Factory Rules
        name: 'AzureDataFactory_Portal'
        properties: {
          description: 'Required for Data Factory portal authoring and monitoring'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 5400
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: [
            'adf.azure.com'
          ]
        }
      }
      {// !!
        name: 'AzureDataFactory_SelfHostedIR'
        properties: {
          description: 'Required for self-hosted IR to connect to Data Factory'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'DataFactory.${location}'
          access: 'Allow'
          priority: 5500
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'ServiceBus_InteractiveAuthoring'
        properties: {
          description: 'Required for self-hosted IR interactive authoring'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'ServiceBus'
          access: 'Allow'
          priority: 5600
          direction: 'Outbound'
        }
      }
      {// !!
        name: 'Microsoft_Downloads'
        properties: {
          description: 'Required for self-hosted IR updates from Microsoft'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 5700
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: [
            'download.microsoft.com'
          ]
        }
      }
      {
        name: 'Allow_VNet_Outbound'
        properties: {
            description: 'Allow traffic to other subnets in same VNet'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 3000
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      // DEBUG RULE - UNCOMMENT ONLY FOR TROUBLESHOOTING
      // WARNING: This allows ALL outbound traffic - use for connectivity debugging
      // To enable: Remove the /* */ comments from the rule below
      /*
      {
        name: 'DEBUG_AllowAllOutbound_TEMPORARY'
        properties: {
            description: 'DEBUG ONLY: Allow all outbound for troubleshooting connectivity issues. REMOVE AFTER DEBUGGING!'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '*'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 4000
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      */
    ]
  }
}

// NSG Flow Logs - Note: This requires Network Watcher to exist in the target region
resource nsgFlowLog 'Microsoft.Network/networkWatchers/flowLogs@2023-05-01' = if (enableFlowLogs && !empty(storageAccountId)) {
  name: '${networkWatcherName}/flowlog-${name}'
  location: location
  tags: tags
  properties: {
    targetResourceId: cmnNsg.id
    storageId: storageAccountId
    enabled: true
    retentionPolicy: {
      days: flowLogRetentionDays
      enabled: true
    }
    format: {
      type: 'JSON'
      version: 2
    }
  }
}

output nsgId string = cmnNsg.id
output flowLogId string = enableFlowLogs && !empty(storageAccountId) ? nsgFlowLog.id : ''
