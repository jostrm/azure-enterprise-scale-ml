// ================================================================
// CLOUDFLARE TUNNEL VM DEPLOYMENT
// This module deploys a lightweight VM to run the Cloudflare Tunnel agent
// for secure access to private Azure Container Apps (ACA)
// ================================================================

// ============================================================================
// ARCHITECTURE:
// User → DNS (domain-specific-ai-sourcing-dev.internal.ericsson.com)
//      → Cloudflare (with Tunnel)
//      → Cloudflare Tunnel Agent (in Azure VM/Container Instance)
//      → Private ACA FQDN (e.g., gentleflower-2e0ff142.swedencentral.azurecontainerapps.io)
// ============================================================================

// ============================================================================
// ADVANTAGES:
// - Maintains ACA as private (security compliant)
// - No reverse proxy complexity on the ACA side
// - Works with Ericsson's security policies (outbound-only connections)
// - Minimal latency (direct tunnel connection)
// - No public IP exposure on Azure resources
// - Cloudflare handles DDoS protection and WAF
// ============================================================================


param location string
param vnetName string
param subnetName string
param vmSize string = 'Standard_B2s' // Small, cost-effective
param adminUsername string = 'azureuser'
@secure()
param adminPassword string
param cloudflaredToken string

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

resource vm 'Microsoft.Compute/virtualMachines@2023-03-01' = {
  name: 'vm-cloudflare-tunnel'
  location: location
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
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'Standard_LRS'
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
