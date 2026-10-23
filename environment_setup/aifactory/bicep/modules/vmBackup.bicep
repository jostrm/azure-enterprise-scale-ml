// ============================================================================
// Opt-in Azure Backup for one existing VM (enableVmBackup, default false).
// Creates the Recovery Services vault and its daily policy when absent, or updates them in place
// (same name = reuse), then protects the VM. Trusted Launch VMs can only be protected by an
// Enhanced (V2) policy, so the policy is V2. Soft delete stays at the platform default (enabled).
// Contract: environment_setup/unit-tests/test-bicep/unit/test_defender_compute_baseline.py
// ============================================================================

@description('Name of an existing VM in this resource group.')
param vmName string

@description('Location of the vault: the VM location.')
param location string

@description('Tags for the vault.')
param tags object = {}

@description('Recovery Services vault in this resource group: created when absent, reused when it exists.')
param vaultName string = 'rsv-${vmName}'

@description('Backup policy name in the vault.')
param policyName string = 'aif-vm-daily-enhanced'

@description('Daily backup time (UTC, HH:mm).')
param backupTimeUtc string = '01:00'

@description('Days a daily recovery point is kept.')
@minValue(7)
@maxValue(9999)
param retentionDays int = 30

var scheduleTime = '2026-01-01T${backupTimeUtc}:00Z'
var containerName = 'iaasvmcontainer;iaasvmcontainerv2;${resourceGroup().name};${vmName}'
var protectedItemName = 'vm;iaasvmcontainerv2;${resourceGroup().name};${vmName}'

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' existing = {
  name: vmName
}

resource vault 'Microsoft.RecoveryServices/vaults@2024-04-01' = {
  name: vaultName
  location: location
  tags: tags
  sku: {
    name: 'RS0'
    tier: 'Standard'
  }
  properties: {}
}

resource policy 'Microsoft.RecoveryServices/vaults/backupPolicies@2024-04-01' = {
  parent: vault
  name: policyName
  properties: {
    backupManagementType: 'AzureIaasVM'
    policyType: 'V2'
    instantRpRetentionRangeInDays: 7
    timeZone: 'UTC'
    schedulePolicy: {
      schedulePolicyType: 'SimpleSchedulePolicyV2'
      scheduleRunFrequency: 'Daily'
      dailySchedule: {
        scheduleRunTimes: [
          scheduleTime
        ]
      }
    }
    retentionPolicy: {
      retentionPolicyType: 'LongTermRetentionPolicy'
      dailySchedule: {
        retentionTimes: [
          scheduleTime
        ]
        retentionDuration: {
          count: retentionDays
          durationType: 'Days'
        }
      }
    }
  }
}

#disable-next-line use-parent-property
resource protectedItem 'Microsoft.RecoveryServices/vaults/backupFabrics/protectionContainers/protectedItems@2024-04-01' = {
  name: '${vault.name}/Azure/${containerName}/${protectedItemName}'
  properties: {
    protectedItemType: 'Microsoft.Compute/virtualMachines'
    policyId: policy.id
    sourceResourceId: vm.id
  }
}

@description('Recovery Services vault resource ID.')
output vaultId string = vault.id
