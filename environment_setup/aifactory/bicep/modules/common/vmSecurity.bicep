// ============================================================================
// Defender for Cloud compute baseline shared by every AI Factory VM module.
// Import these values instead of repeating them, so the baseline lives in one place:
//   import { trustedLaunch, windowsGen2Image, windowsPatchSettings } from 'common/vmSecurity.bicep'
//
// - Generation 2 images only. microsoft-dsvm dsvm-win-2022:winserver-2022 and dsvm-win-2019:server-2019
//   are Generation 1 only (az vm image show --query hyperVGeneration -> V1) and cannot use Trusted Launch.
// - Trusted Launch: Secure Boot + vTPM (needed by the Guest Attestation extension).
// - Update assessment by the platform: "Machines should be configured to periodically check for
//   missing system updates".
// Contract: environment_setup/unit-tests/test-bicep/unit/test_defender_compute_baseline.py
// ============================================================================

@export()
@description('Windows Server 2022 Datacenter Azure Edition. Generation 2, Trusted Launch capable (verified 2026-10-23). Replaces the Gen1-only Data Science VM image.')
var windowsGen2Image = {
  publisher: 'MicrosoftWindowsServer'
  offer: 'WindowsServer'
  sku: '2022-datacenter-azure-edition'
  version: 'latest'
}

@export()
@description('Ubuntu Server 24.04 LTS. Generation 2, Trusted Launch capable (verified 2026-10-23). Same image as the Linux runner VM.')
var linuxGen2Image = {
  publisher: 'Canonical'
  offer: 'ubuntu-24_04-lts'
  sku: 'server'
  version: 'latest'
}

@export()
@description('Trusted Launch security profile without encryptionAtHost; union it with { encryptionAtHost: <bool> }.')
var trustedLaunch = {
  securityType: 'TrustedLaunch'
  uefiSettings: {
    secureBootEnabled: true
    vTpmEnabled: true
  }
}

@export()
@description('Windows: Windows Update installs patches as before; the platform assesses missing updates every 24 hours.')
var windowsPatchSettings = {
  enableHotpatching: false
  patchMode: 'AutomaticByOS'
  assessmentMode: 'AutomaticByPlatform'
}

@export()
@description('Linux: the image keeps its default patching; the platform assesses missing updates every 24 hours.')
var linuxPatchSettings = {
  patchMode: 'ImageDefault'
  assessmentMode: 'AutomaticByPlatform'
}
