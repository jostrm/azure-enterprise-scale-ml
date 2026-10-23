---
id: compute-security-baseline
status: observed
sources:
  - environment_setup/aifactory/bicep/modules/common/vmSecurity.bicep
  - environment_setup/aifactory/bicep/modules/vmSecurityExtensions.bicep
  - environment_setup/aifactory/bicep/modules/vmBackup.bicep
  - environment_setup/aifactory/bicep/modules/virtualMachinePrivate.bicep
  - environment_setup/aifactory/bicep/modules/virtualMachinePublic.bicep
  - environment_setup/aifactory/bicep/esml-common/modules-common/avdSessionHost.bicep
  - environment_setup/aifactory/bicep/esml-common/modules-common/cloudflareTunnelVm.bicep
  - environment_setup/aifactory/bicep/modules/aksCluster.bicep
  - environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/02-core-infrastructure.bicep
  - environment_setup/aifactory/bicep/scripts/admin-vm-exists.sh
  - environment_setup/aifactory/bicep/scripts/ensure-encryption-at-host.sh
  - bootstrap/lib/runner_bootstrap.py
  - bootstrap/lib/create-new-aifactory-scaleset.sh
  - bootstrap/lib/factory_lifecycle.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_defender_compute_baseline.py
  - environment_setup/unit-tests/test-bicep/unit/test_runner_bootstrap.py
  - environment_setup/unit-tests/test-bicep/unit/test_pipeline_feature_contracts.py
  - environment_setup/unit-tests/test-bicep/unit/test_resource_fingerprint_churn.py
graph_symbols:
  - environment_setup/aifactory/bicep/modules/common/vmSecurity.bicep
  - bootstrap/lib/runner_bootstrap.py::function:ensure_vm
  - bootstrap/lib/runner_bootstrap.py::function:runner_identity_matches
reviewed_source: 'd865dea0 + this change; observed 2026-10-23'
---
# Compute security baseline (VMs, runner VMs, AKS)

## Observed

Every VM AI Factory provisions follows one Defender for Cloud baseline, kept in
`modules/common/vmSecurity.bicep` (exported values) and `modules/vmSecurityExtensions.bicep`
(extensions). `test_defender_compute_baseline.py` compiles each VM module and fails when a new
non-debug Bicep file declares a VM or VM scale set outside the list, or when a script creates one
with `az vm create` / `az vmss create` without the Trusted Launch, encryption-at-host and identity flags.

| Defender for Cloud recommendation | Implementation |
|---|---|
| Encryption at host / Azure Disk Encryption or EncryptionAtHost | `securityProfile.encryptionAtHost: enableEncryptionAtHost` (default true); AKS node pools `enableEncryptionAtHost` |
| No Gen1 disks; Trusted Launch | Generation 2 images only, `securityType: TrustedLaunch`, Secure Boot + vTPM |
| Guest Configuration extension | System-assigned identity + `AzurePolicyforWindows` / `AzurePolicyforLinux` (auto-upgrade) |
| Guest Attestation extension | `GuestAttestation` (Windows/LinuxAttestation), installed before Guest Configuration |
| Periodic check for missing system updates | `patchSettings.assessmentMode: AutomaticByPlatform` (Windows keeps `AutomaticByOS` patching; Linux `ImageDefault`) |
| SSD disks | OS and data disks `StandardSSD_LRS` or Premium (`@allowed` blocks `Standard_LRS`) |
| AKS Defender profile, Azure Policy add-on, diagnostic logs | `securityProfile.defender` with the Log Analytics workspace, `addonProfiles.azurepolicy`, diagnostic setting (`kube-audit-admin`, `kube-controller-manager`, `kube-scheduler`, `cluster-autoscaler`, `guard`; `kube-apiserver` and `kube-audit` are left out for volume and cost) |

Images, verified read-only with `az vm image show` on 2026-10-23:

- Windows: `MicrosoftWindowsServer:WindowsServer:2022-datacenter-azure-edition` (V2,
  TrustedLaunchAndConfidentialVmSupported). It replaces `microsoft-dsvm:dsvm-win-2022:winserver-2022`
  and `dsvm-win-2019:server-2019`, which are V1 only. The only Gen2 DSVM SKUs
  (`dsvm-win-2019:server-2019-gen2`, `dsvm-windows:server-2019-g2`) were last published in 2021.
- Linux: `Canonical:ubuntu-24_04-lts:server` (V2, TrustedLaunchSupported), the runner image.

The plain Windows Server image lacks the DSVM tooling: Miniconda with the TensorFlow/PyTorch/AzureML
conda environments, Jupyter/JupyterLab, R, Julia, VS Code, Visual Studio Community, PyCharm, Azure CLI,
AzCopy, Storage Explorer, Git/Git Bash, SQL Server 2019 Developer + SSMS, Spark standalone, Docker
(Windows containers), CUDA/cuDNN, Power BI Desktop and Microsoft 365. The self-hosted agent path does
not depend on it: `runner-prerequisites.ps1 -InstallMissing` installs git, Python, PowerShell 7, gh,
Azure CLI, Bicep and jq. Data scientists install their own tools or use Azure ML compute instances.

### Existing VMs and backward compatibility

An existing VM is never PUT again (`vmExists`): image, security type and encryption at host cannot
change in place on a running Gen1 DSVM, the admin VM is often the ADO agent running the deployment,
and a redeploy must not rotate the Key Vault password. The common pipelines compute `adminVmExists`
with the read-only `scripts/admin-vm-exists.sh` (fails closed when Azure cannot be read); both project
pipelines detect the project VM (`vmExists`; GHA gained the detection with this change).
Upgrade note: copy the pipeline templates of this release with the submodule bump. An older common
pipeline does not pass `adminVmExists` (default false), so it would PUT an existing Gen1 admin VM again
and fail with `PropertyChangeNotAllowed`. Existing VMs therefore keep their Defender findings until they are
recreated (deallocate is not enough for Gen1 -> Gen2). AKS clusters are only created (`!aksExists`), so
existing clusters keep their node pools; the Azure Policy add-on and Defender profile can be enabled
on them with `az aks enable-addons` / `az aks update --enable-defender`.

### Switches

- `enableEncryptionAtHost` (default true): VMs and AKS node pools. Needs the subscription feature
  `Microsoft.Compute/EncryptionAtHost`; `create-new-aifactory-scaleset.sh` registers it idempotently in
  the Dev subscription (`aif_register_encryption_at_host_feature`). Stage/prod subscriptions need the
  same one-time `az feature register --namespace Microsoft.Compute --name EncryptionAtHost` followed by
  `az provider register --namespace Microsoft.Compute`. Every pipeline step that forwards the flag first runs
  `scripts/ensure-encryption-at-host.sh`: when the flag is true and the step can create a VM or AKS cluster,
  it registers the feature if absent and fails with the opt-out hint when it may not. The runner bootstrap reads
  the same key (`enableEncryptionAtHost` / `ENABLE_ENCRYPTION_AT_HOST`) and checks the feature read-only
  before its first write. Set false to opt out.
- `enableVmBackup` (default false): `modules/vmBackup.bicep` creates or reuses a Recovery Services
  vault `rsv-<vmName>` with a daily Enhanced (V2) policy, 30 days retention, and protects the admin or
  project VM (also an existing one). Trusted Launch VMs require the Enhanced policy.

### Runner VMs

`runner_bootstrap.py ensure_vm` creates only absent runner VMs: system-assigned identity, Trusted
Launch with encryption at host, the governance-compliant `AutomaticByPlatform` patch settings (which include
update assessment), StandardSSD OS disk, then Guest Attestation and Guest Configuration via create-only PUTs.
Existing runners are reused unchanged; `runner_identity_matches` accepts the baseline system-assigned
identity plus, at most, the exact deployment UAMI. The platform upgrades both extensions
(`enableAutomaticUpgrade`), so `factory_lifecycle.fingerprint_body` counts only their identity, like the
Defender for Servers extension: an upgrade is not a changed reviewed resource.

### Not done

- Windows Defender Exploit Guard is not enforced. The built-in policy only audits it through Guest
  Configuration (now installed). Attack-surface-reduction rules, network protection and controlled
  folder access belong to Defender for Endpoint (Defender for Servers P2 via
  `enableDefenderforAISubLevel` with `enableAdminVM`) or Intune baselines, where block mode can be
  tested against the data-science tooling first.
- Subscription governance outside AI Factory can still undo parts of the baseline: in MCAPS subscriptions it set
  runner OS disks to Standard HDD (observed 2026-10-15..23, see [[Lifecycle-and-Recovery]]).
- Extensions are not retried on an existing VM: if Guest Attestation or Guest Configuration fails on the
  first run, later runs skip the VM (`vmExists`); install them by hand or redeploy the VM.
- Legacy and manual entrypoints (`esml-project/22-main.bicep`, `23-add-dsvm`, `24-add-aks`,
  `modules/machineLearning.bicep`) pass no `vmExists`/`aksExists`: they create new resources only.
- The backup vault keeps platform defaults (geo-redundant storage, public network access setting).
- ADO consumers whose `variables.yaml` lacks the two new keys get an unexpanded `$(...)` macro, as for
  every other flag; merge the template keys.
- Disk encryption with customer-managed keys (disk encryption sets) for VMs is not added; AKS keeps
  its existing `cmk` path.
