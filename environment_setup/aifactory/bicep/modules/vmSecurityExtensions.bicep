// ============================================================================
// Defender for Cloud VM extensions for one existing Trusted Launch VM:
// - Guest Attestation (Microsoft.Azure.Security.WindowsAttestation|LinuxAttestation): "Guest Attestation
//   extension should be installed on supported Windows/Linux virtual machines". Needs Secure Boot + vTPM.
// - Guest Configuration (Microsoft.GuestConfiguration AzurePolicyforWindows|AzurePolicyforLinux): "Guest
//   Configuration extension should be installed on machines". Uses the VM's system-assigned identity.
// The two installs run one after the other: parallel extension operations on one VM can conflict.
// Contract: environment_setup/unit-tests/test-bicep/unit/test_defender_compute_baseline.py
// ============================================================================

@description('Name of an existing VM in this resource group, created with Trusted Launch and a system-assigned identity.')
param vmName string

@description('Location of the VM.')
param location string

@description('Operating system of the VM.')
@allowed([
  'Windows'
  'Linux'
])
param osType string

@description('Tags for the extension resources.')
param tags object = {}

var guestConfiguration = {
  Windows: {
    name: 'AzurePolicyforWindows'
    type: 'ConfigurationforWindows'
  }
  Linux: {
    name: 'AzurePolicyforLinux'
    type: 'ConfigurationForLinux'
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' existing = {
  name: vmName
}

resource guestAttestation 'Microsoft.Compute/virtualMachines/extensions@2024-07-01' = {
  parent: vm
  name: 'GuestAttestation'
  location: location
  tags: tags
  properties: {
    publisher: osType == 'Windows' ? 'Microsoft.Azure.Security.WindowsAttestation' : 'Microsoft.Azure.Security.LinuxAttestation'
    type: 'GuestAttestation'
    typeHandlerVersion: '1.0'
    autoUpgradeMinorVersion: true
    enableAutomaticUpgrade: true
    settings: {
      AttestationConfig: {
        MaaSettings: {
          maaEndpoint: ''
          maaTenantName: 'GuestAttestation'
        }
        AscSettings: {
          ascReportingEndpoint: ''
          ascReportingFrequency: ''
        }
        useCustomToken: 'false'
        disableAlerts: 'false'
      }
    }
  }
}

resource guestConfigurationExtension 'Microsoft.Compute/virtualMachines/extensions@2024-07-01' = {
  parent: vm
  name: guestConfiguration[osType].name
  location: location
  tags: tags
  properties: {
    publisher: 'Microsoft.GuestConfiguration'
    type: guestConfiguration[osType].type
    typeHandlerVersion: '1.0'
    autoUpgradeMinorVersion: true
    enableAutomaticUpgrade: true
    settings: {}
    protectedSettings: {}
  }
  dependsOn: [
    guestAttestation
  ]
}
