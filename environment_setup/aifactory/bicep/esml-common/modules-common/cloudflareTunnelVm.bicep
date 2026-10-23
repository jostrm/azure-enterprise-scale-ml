// ================================================================
// CLOUDFLARE TUNNEL VM DEPLOYMENT
// This module deploys a lightweight VM to run the Cloudflare Tunnel agent
// for secure access to private Azure Container Apps (ACA)
// ================================================================

// ============================================================================
// ARCHITECTURE:
// User → DNS (your-app.internal.example.com)
//      → Cloudflare (with Tunnel)
//      → Cloudflare Tunnel Agent (in Azure VM/Container Instance)
//      → Private ACA FQDN (e.g., gentleflower-2e0ff142.swedencentral.azurecontainerapps.io)
// ============================================================================

// ============================================================================
// ADVANTAGES:
// - Maintains ACA as private (security compliant)
// - No reverse proxy complexity on the ACA side
// - Works with your organization's security policies (outbound-only connections)
// - Minimal latency (direct tunnel connection)
// - No public IP exposure on Azure resources
// - Cloudflare handles DDoS protection and WAF
// ============================================================================


import { linuxGen2Image, linuxPatchSettings, trustedLaunch } from '../../modules/common/vmSecurity.bicep'

param location string
param vnetName string
param subnetName string
param vmSize string = 'Standard_B2s_v2' // Small, cost-effective; Gen2 and encryption at host capable (az vm list-skus, 2026-10-23)
param adminUsername string = 'azureuser'
@secure()
param adminPassword string
param cloudflaredToken string
@description('Defender for Cloud: encryption at host. Needs the subscription feature Microsoft.Compute/EncryptionAtHost. Set false to opt out.')
param enableEncryptionAtHost bool = true
@description('Opt-in Azure Backup: Recovery Services vault + daily Enhanced policy, protecting this VM.')
param enableVmBackup bool = false

resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' existing = {
  name: vnetName
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' existing = {
  parent: vnet
  name: subnetName
}

resource nic 'Microsoft.Network/networkInterfaces@2023-05-01' = {
  name: 'nic-cloudflare-tunnel'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: subnet.id
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: 'vm-cloudflare-tunnel'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    osProfile: {
      computerName: 'cf-tunnel'
      adminUsername: adminUsername
      adminPassword: adminPassword
      customData: base64('''
#!/bin/bash
# Install cloudflared
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Configure tunnel (token passed via parameter)
sudo cloudflared service install ${cloudflaredToken}
''')
      linuxConfiguration: {
        provisionVMAgent: true
        patchSettings: linuxPatchSettings
      }
    }
    securityProfile: union(trustedLaunch, {
      encryptionAtHost: enableEncryptionAtHost
    })
    storageProfile: {
      imageReference: linuxGen2Image
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS' // never Standard_LRS (HDD)
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
        }
      ]
    }
  }
}

module securityExtensions '../../modules/vmSecurityExtensions.bicep' = {
  name: 'vmSecExt-vm-cloudflare-tunnel'
  params: {
    vmName: vm.name
    location: location
    osType: 'Linux'
  }
}

module backup '../../modules/vmBackup.bicep' = if (enableVmBackup) {
  name: 'vmBackup-vm-cloudflare-tunnel'
  params: {
    vmName: vm.name
    location: location
  }
  dependsOn: [
    securityExtensions
  ]
}