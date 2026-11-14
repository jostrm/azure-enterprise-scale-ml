# Compaction report

This branch was made by compact-repo. It holds what the entry points use; everything else was removed in one commit.

| Item | Value |
|---|---|
| Base commit | `c8ab933fb1ea58ae799e962bc21d568a154745df` |
| Target branch | `release/v1.26` |
| Profile hash | `40c6d9b497a288d21c95495d84e0455207e1119606479623c8c185873f59cf11` |
| Tool | compact-repo 0.1.0rc1 |

## Summary

|  | Files | Size |
|---|---:|---:|
| Before | 3,105 | 294.9 MB (309,196,475 bytes) |
| Kept | 3,030 | 294.5 MB (308,845,225 bytes) |
| Dropped (saved) | 75 | 343.0 KB (351,250 bytes) |

### By class

| Class | Files | Size | Kept | Dropped |
|---|---:|---:|---:|---:|
| root | 865 | 9.8 MB | 865 | 0 |
| pinned | 958 | 79.6 MB | 958 | 0 |
| dependency | 694 | 163.4 MB | 694 | 0 |
| follower | 512 | 41.6 MB | 511 | 1 |
| report | 2 | 146.9 KB | 2 | 0 |
| forced-drop | 74 | 321.9 KB | 0 | 74 |

## Entry points and pinned files

| File | Reason |
|---|---|
| `.claude/hooks/no_idle_wait.py` | kept by the profile (keep: .claude/**) |
| `.claude/settings.json` | kept by the profile (keep: .claude/**) |
| `.claude/skills/task-status/SKILL.md` | kept by the profile (keep: .claude/**) |
| `.compact-repo.yml` | kept by the profile (keep: .compact-repo.yml) |
| `.gitattributes` | kept by the profile (keep: .gitattributes) |
| `.github/copilot-instructions.md` | kept by the profile (keep: .github/copilot-instructions.md) |
| `.github/workflows/infrastructure-tests.yml` | entry point: Purple CI: runs on every push to any branch (unit on Ubuntu and Windows, syntax, bicep). |
| `.github/workflows/verify-aifactory-dev.yml` | entry point: Purple CI: offline unit tests on pushes that touch copy_to_local_settings/** or unit-tests/**. |
| `.github/workflows/verify-aifactory-prod.yml` | entry point: Purple CI: manual placeholder; reaches no repo file. |
| `.github/workflows/verify-aifactory-stage.yml` | entry point: Purple CI: manual placeholder; reaches no repo file. |
| `.gitignore` | kept by the profile (keep: .gitignore) |
| `00-start.sh` | entry point: Consumer entry point, all layouts (v1.24 legacy paths included, R6). |
| `01-start-v125-and-above.sh` | entry point: Consumer entry point, registered layout (v1.25 and above). |
| `AGENTS.md` | kept by the profile (keep: AGENTS.md) |
| `CLAUDE.md` | kept by the profile (keep: CLAUDE.md) |
| `CODE_OF_CONDUCT.md` | kept by the profile (keep: CODE_OF_CONDUCT.md) |
| `CONTRIBUTING.md` | kept by the profile (keep: CONTRIBUTING.md) |
| `LICENSE` | kept by the profile (keep: LICENSE) |
| `README.md` | kept by the profile (keep: README.md) |
| `RELEASE_120.md` | kept by the profile (keep: RELEASE_120.md) |
| `RELEASE_123.md` | kept by the profile (keep: RELEASE_123.md) |
| `RELEASE_124.md` | kept by the profile (keep: RELEASE_124.md) |
| `RELEASE_125.md` | kept by the profile (keep: RELEASE_125.md) |
| `ROADMAP_MAIN.md` | kept by the profile (keep: ROADMAP_MAIN.md) |
| `SECURITY.md` | kept by the profile (keep: SECURITY.md) |
| `SUPPORT.md` | kept by the profile (keep: SUPPORT.md) |
| `__init__.py` | kept by the profile (keep: __init__.py) |
| `bootstrap/.gitignore.template` | entry point: Merged into the consumer's .gitignore by registered_setup.py and copied by 01-aif-copy-aifactory-templates.sh. |
| `bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh` | referenced by jostrm/azure-aifactory-config, template-files/creation-workflow/bootstrap/lib/create-new-aifactory-scaleset.sh, line 1607 |
| `bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh` | referenced by jostrm/azure-aifactory-config, template-files/creation-workflow/bootstrap/lib/create-new-aifactory-scaleset.sh, line 1603 |
| `bootstrap/ADO-azurefactory.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/ADO-create-new-aifactory-scaleset.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/AIFactory-lifecycle.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/ALL-create-new-aifactory-scaleset.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/GHA-azurefactory.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/GHA-create-new-aifactory-scaleset.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/GHA-update-aifactory-and-run-project.sh` | entry point: AIF_DUAL_LAYOUT_LAUNCHERS: 00-start.sh installs these launchers into the consumer root by bare name (bootstrap/lib/layout_router.sh); the user runs them from there. |
| `bootstrap/azurefactory.sh` | entry point: Registered-layout launcher that registered_setup.py installs into the consumer root (with AIFactory-lifecycle.sh and the provider wrappers). |
| `bootstrap/lib/agent_chat_entry.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/aifactory_private_dns.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/aifactory_scaleset_config.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/aifactory_vpn_profile.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/all-factories-dashboard.bicep` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/all_factories_dashboard.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/bootstrap_no_delete.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/common_network_preservation.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/factory_deletion_pipeline.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/factory_enrollment.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/factory_enrollment_entry.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/factory_lifecycle.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/factory_lifecycle_contract.txt` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/github_environments.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/hub_lock_foundation.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/hub_private_transition.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/initialize_azurefactory.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/layout_router.sh` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/project_deployment.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/project_environment.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/provider_repository_state.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/registered_creation.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/registered_personas.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/registered_prerequisites.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/registered_repository.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/registered_setup.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/release_version.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/release_version.sh` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/runner-only-registration.sh` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/runner-prerequisites.ps1` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/runner-prerequisites.sh` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/runner-registration.ps1` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/runner-registration.sh` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/runner_bootstrap.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/simple-app-gateway-network.bicep` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/simple-app-gateway.bicep` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/lib/workflow_run_monitor.py` | entry point: 01-start-v125-and-above.sh (bootstrap/lib/registered_setup.py) copies this whole folder into the consumer's lib/, and 00-start.sh installs AIF_DUAL_LAYOUT_LIBRARIES from it by bare name (layout_router.sh). The Factory API runs factory_lifecycle.py and its siblings from the submodule and vendors most of the folder byte for byte. |
| `bootstrap/templates/azurefactory/register.json` | entry point: The Factory API commits factory-lifecycle-*.yml into the consumer repo (.github/workflows/factory-lifecycle.yml or aifactory/pipelines/factory-lifecycle.yml) and hub_private_probe.py into .azurefactory/; it requires them in purple's GitHub tree (pink registered_repository.py). |
| `bootstrap/templates/factory-lifecycle-ado.yml` | entry point: The Factory API commits factory-lifecycle-*.yml into the consumer repo (.github/workflows/factory-lifecycle.yml or aifactory/pipelines/factory-lifecycle.yml) and hub_private_probe.py into .azurefactory/; it requires them in purple's GitHub tree (pink registered_repository.py). |
| `bootstrap/templates/factory-lifecycle-gha.yml` | entry point: The Factory API commits factory-lifecycle-*.yml into the consumer repo (.github/workflows/factory-lifecycle.yml or aifactory/pipelines/factory-lifecycle.yml) and hub_private_probe.py into .azurefactory/; it requires them in purple's GitHub tree (pink registered_repository.py). |
| `bootstrap/templates/factory-lifecycle-single-writer-ado.yml` | entry point: The Factory API commits factory-lifecycle-*.yml into the consumer repo (.github/workflows/factory-lifecycle.yml or aifactory/pipelines/factory-lifecycle.yml) and hub_private_probe.py into .azurefactory/; it requires them in purple's GitHub tree (pink registered_repository.py). |
| `bootstrap/templates/factory-lifecycle-single-writer-gha.yml` | entry point: The Factory API commits factory-lifecycle-*.yml into the consumer repo (.github/workflows/factory-lifecycle.yml or aifactory/pipelines/factory-lifecycle.yml) and hub_private_probe.py into .azurefactory/; it requires them in purple's GitHub tree (pink registered_repository.py). |
| `bootstrap/templates/hub_private_probe.py` | entry point: The Factory API commits factory-lifecycle-*.yml into the consumer repo (.github/workflows/factory-lifecycle.yml or aifactory/pipelines/factory-lifecycle.yml) and hub_private_probe.py into .azurefactory/; it requires them in purple's GitHub tree (pink registered_repository.py). |
| `bootstrap/ui/terminal.sh` | entry point: Sourced by every launcher; registered_setup.py copies the folder into the consumer's ui/. |
| `copy_my_subfolders_to_my_grandparent/.gitignore` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/01_init_templates_ALL.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/02_update_templates_QUICK.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/SAP/ds_diabetes/Project000/STEP02b_MASTER_IN_csv_2_Project_IN_parquet_dsXX.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/SAP/ds_diabetes/Project000/STEP04_PRJ_WRITEBACK_2_DB_Upsert.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/SAP/ds_diabetes/Project000/STEP04_ShareBack_2_MASTER.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/SAP/ds_diabetes/Project000/old/STEP02a_MASTER_IN_csv_2_Project_IN_csv_n_OUT_pq.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/SAP/ds_diabetes/STEP01a_MR_ds01_Source_2_MASTER_IN_as_DELTA.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/SAP/ds_diabetes/STEP01b_MR_ds01_Source_2_MASTER_IN_v14.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/SQL_CSV_PARQUET_abc/STEP00_DEMO_PRJ002_M11_Init_DB.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/MASTER/STEP00_DEMO_PRJ002_M11_Init_DB_1.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/PROJECT000/LakeOnly/STEP03_IN_2_GOLD_PowerBI_LakeOnly.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/PROJECT000/LakeOnly/STEP03_IN_2_GOLD_SCORING_wTrigger.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/PROJECT000/LakeOnly/STEP03_IN_2_GOLD_TRAIN_v1_3.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/PROJECT000/WriteBack2SQL/STEP03_IN_2_GOLD_PowerBI.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/PROJECT000/WriteBack2SQL/STEP03_IN_2_GOLD_SCORING.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/PROJECT000/WriteBack2SQL/STEP03_IN_2_GOLD_TRAIN.zip` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/adf/v1_3/sql_demo_scripts/M11_AzureSQLDB_create_tables.sql` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/.gitignore` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/copy.example.json` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/job-payload.example.json` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/main.bicep` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/parameters.example.json` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/prepare_run.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/tests/test_templates.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/microsoft-fabric/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dataops/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dbx/01_dataset_paths.dbc` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dbx/M11.dbc` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/dbx/esml_v14_aml_v145.dbc` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/genaiops/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/10-get_environment.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/21-train_in_2_gold_train_pipeline.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/31-deploy_and_smoketest_batch_scoring.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/32-deploy_online_aks.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/32-smoke_test_online.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/02_cicd-ado-gha_mlops/azure_devops/build_pipeline/ESML-v14-project000_M00-DevTest-clean.json` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/02_cicd-ado-gha_mlops/azure_devops/build_pipeline/ESML-v14-project000_M00-DevTest-clean.yml` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/02_cicd-ado-gha_mlops/azure_devops/release/release-test-prod-v14.json` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/02_cicd-ado-gha_mlops/github_actions/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/.gitignore` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/ado/ml-factory.yml` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/ado/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/github/ml-factory.yml` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/github/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/scripts/bootstrap.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/scripts/ci.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_selection_ci.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/LICENSE` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/01-esml-test-steps.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/10-get_environment.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/21-bronze_2_gold.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/22-train_automl.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/23-compare_scoring_register.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/31-deploy_online_aks.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/31-test_online_aks.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/40-deploy_batch_aml.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/40-test_batch_aml.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/01-esml-test-steps.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/10-get_environment.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/21-bronze_2_gold_local.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/21-bronze_2_gold_pipeline.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_automl.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_manual_pipeline.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/23-compare_scoring_register.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/31-deploy_online_aks.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/31-test_online_aks.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/40-deploy_batch_aml.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/1a_R&D_TRAIN_M00_No_rehydrate.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/1b_R&D_TRAIN_M00.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/2a_PROD_TRAIN_PIPE_AML_AutoML.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/2b_PROD_TRAIN_PIPE_DBX_all_steps.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/2c_PROD_TRAIN_PIPE_MIX_some_steps_adv_Databricks.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/2d_PROD_TRAIN_PIPE_ManualML.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/3a_PROD_INF_BATCH_Pipeline.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/3b_PROD_INF_BATCH_Pipeline_DBX.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/3c_PROD_INF_ONLINE_Adv_Private_AKS_Endpoint.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/3d_PROD_INF_ONLINE_Private_AKS_Endpoint.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/MLmodel` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/conda.yaml` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/model.pkl` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/python_env.yaml` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/requirements.txt` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/score.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_aml_sdkv2_versus_sdkv1/10-v1-setup-computeinstance.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_aml_sdkv2_versus_sdkv1/10-v2-setup-computeinstance.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_aml_sdkv2_versus_sdkv1/20-v2-deploy-online-ep.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/00_esmladmin_scripts/1_Lake_init_mount.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/azure_functions.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/esml_lake_design/esml_lake.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/import/azureml_helper.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/import/pip_libs.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/00_project_settings/esml_project.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/00_model_settings/01_dataset_paths.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/10_in2silver_ds01_diabetes.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/10_in2silver_ds02_other.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/20_merge_2_gold.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/21_split_GOLD_and_register_datasets.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_scoring_gold.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_code/your_train_code.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_register.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/00_model_settings/01_dataset_paths.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds02_other.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/21_split_GOLD_and_register_datasets.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_scoring_gold.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_code/your_train_code.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_register.py` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/readme.md` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_templates_esml_v14_2022-06-2023_aml_v143/00_SQL_DDL.ipynb` | kept by the profile (keep: copy_my_subfolders_to_my_grandparent/**) |

1,623 more rows are not shown; plan.json has all of them.

## Largest dropped files

| File | Size | Reason |
|---|---:|---|
| `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/README.md` | 21.1 KB | docs: nothing it belongs to is kept |
| `esml/azure_provisioning/azure_devops_pipelines/Release/Test_Prod/Release-Online-Test_Prod.json` | 20.1 KB | dropped by the profile (drop: esml/azure_provisioning/azure_devops_pipelines/Release/Test_Prod/Release-Online-Test_Prod.json) |
| `environment_setup/aifactory/bicep/esml-util/000-delete-subnets-for-project.ps1` | 18.7 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/esml-util/000-delete-subnets-for-project.ps1) |
| `environment_setup/aifactory/bicep/esml-common/modules-common/nsgCommonScoring.json` | 18.5 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/esml-common/modules-common/nsgCommonScoring.json) |
| `environment_setup/aifactory/azure_dashboards/ESML-AIFactory-1.json` | 18.2 KB | dropped by the profile (drop: environment_setup/aifactory/azure_dashboards/ESML-AIFactory-1.json) |
| `environment_setup/aifactory/azure_dashboards/ESML-AIFactory-DEV.json` | 16.1 KB | dropped by the profile (drop: environment_setup/aifactory/azure_dashboards/ESML-AIFactory-DEV.json) |
| `esml/azure_provisioning/azure_devops_pipelines/Release/Dev/Release-Online-Dev.json` | 11.7 KB | dropped by the profile (drop: esml/azure_provisioning/azure_devops_pipelines/Release/Dev/Release-Online-Dev.json) |
| `esml/azure_provisioning/azure_devops_pipelines/Build_pipelines/Dev/ESML-project002_M03-Dev.json` | 10.9 KB | dropped by the profile (drop: esml/azure_provisioning/azure_devops_pipelines/Build_pipelines/Dev/ESML-project002_M03-Dev.json) |
| `environment_setup/aifactory/bicep/esml-util/23-install-sdks-on-win11.ps1` | 10.9 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/esml-util/23-install-sdks-on-win11.ps1) |
| `esml/azure_provisioning/azure_devops_pipelines/Build_pipelines/Test_Prod/ESML-project002_M03-Test_Prod.json` | 10.7 KB | dropped by the profile (drop: esml/azure_provisioning/azure_devops_pipelines/Build_pipelines/Test_Prod/ESML-project002_M03-Test_Prod.json) |
| `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-project-identity.json` | 9.0 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-project-identity.json) |
| `environment_setup/aifactory/bicep/esml-util/12-GENAI-update-ip-rule-cmd.sh` | 8.8 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/esml-util/12-GENAI-update-ip-rule-cmd.sh) |
| `environment_setup/aifactory/bicep/esml-util/000-cost-from-rg-tag.ps1` | 8.3 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/esml-util/000-cost-from-rg-tag.ps1) |
| `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/deleteAllCapHosts.ps1` | 7.6 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/deleteAllCapHosts.ps1) |
| `environment_setup/aifactory/azure_dashboards/ESML-AIFactory-Dev-v2.json` | 7.5 KB | dropped by the profile (drop: environment_setup/aifactory/azure_dashboards/ESML-AIFactory-Dev-v2.json) |
| `environment_setup/aifactory/azure_dashboards/ESML-AIFactory-v2.json` | 7.5 KB | dropped by the profile (drop: environment_setup/aifactory/azure_dashboards/ESML-AIFactory-v2.json) |
| `environment_setup/aifactory/bicep/modules/monitoring/amplsHub.bicep` | 6.6 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/modules/monitoring/amplsHub.bicep) |
| `environment_setup/aifactory/bicep/esml-project/21-network.bicep` | 6.6 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/esml-project/21-network.bicep) |
| `environment_setup/aifactory/bicep/modules/verify-acr-rbac.bicep` | 6.3 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/modules/verify-acr-rbac.bicep) |
| `environment_setup/aifactory/bicep/modules/databricksAssets.bicep` | 5.9 KB | dropped by the profile (drop: environment_setup/aifactory/bicep/modules/databricksAssets.bicep) |

## Dropped by top-level folder

| Folder | Files | Size |
|---|---:|---:|
| `environment_setup/` | 71 | 289.6 KB |
| `esml/` | 4 | 53.4 KB |

## Kept only by weak evidence

These files are kept because of a path string, a pattern, or a folder that is used as a whole. If such a reference does not really need them, add them to `drop` in the profile.

| Reference | Target | Confidence | Files kept only through it | Size |
|---|---|---|---:|---:|
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/region-report-steps.yaml` line 17 | `**/*.json` | dynamic | 18 | 95.1 MB |
| `bootstrap/01-aif-copy-aifactory-templates.sh` line 66 | `environment_setup/aifactory/` | dynamic | 43 | 3.4 MB |
| `environment_setup/azurefactory-cli/tests/test_documentation_site.py` line 244 | `usecase_code/` | dynamic | 22 | 118.0 KB |
| `environment_setup/install_sdk/user_dev_env_install/AzureML_v1_55_and_v2_1_15/automl_setup.cmd` line 56 | `environment_setup/install_sdk/` | dynamic | 64 | 113.8 KB |
| `00-start.sh` line 25 | `bootstrap/` | dynamic | 2 | 14.3 KB |
| `environment_setup/unit-tests/test-bicep/azure-pipelines.yml` line 69 | `healthmodel/bicep/` | dynamic | 2 | 4.4 KB |
| `bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh` line 28 | `**/.env.template` | dynamic | 1 | 2.6 KB |
| `bootstrap/lib/runner_bootstrap.py` line 379 | `[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*` | dynamic | 4 | 2.6 KB |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` line 3652 | `**/agents.json` | dynamic | 1 | 2.1 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md` line 99 | `environment_setup/install_config_wizard/windows/aifactory-config-windows.zip` | likely | 1 | 43.1 MB |
| `documentation/architecture/infrastructure/Compute-Security-Baseline.md` line 21 | `environment_setup/unit-tests/test-bicep/unit/test_defender_compute_baseline.py` | likely | 2 | 1.3 MB |
| `documentation/v1/00-readme-old-intro.md` line 9 | `esml/images/esml-s01e01-0.png` | likely | 1 | 1.2 MB |
| `esml/z/README.md` line 153 | `esml/images/esml-autolake.png` | likely | 1 | 1.1 MB |
| `esml/z/README.md` line 31 | `esml/images/esml-turnkey.png` | likely | 1 | 1.0 MB |
| `esml/z/README.md` line 210 | `esml/images/esml-oneslider.png` | likely | 1 | 909.6 KB |
| `esml/z/README.md` line 575 | `esml/images/scoring-lake.png` | likely | 1 | 764.3 KB |
| `esml/z/README.md` line 568 | `esml/images/esml-get-scoring.png` | likely | 1 | 736.3 KB |
| `documentation/v1/00-readme-old-intro.md` line 5 | `esml/images/esml-s02e01-4steps.png` | likely | 1 | 630.0 KB |
| `esml/z/README.md` line 160 | `esml/images/esml-s01e01-1.png` | likely | 1 | 569.1 KB |
| `documentation/v1/00-readme-old-intro.md` line 13 | `esml/images/Bicep-1-click.png` | likely | 1 | 402.4 KB |
| `esml/z/README.md` line 194 | `esml/images/esml-autolake-meta.png` | likely | 1 | 275.1 KB |
| `documentation/v1/00-readme-old-intro.md` line 17 | `esml/images/esml-arch-small.png` | likely | 1 | 272.3 KB |
| `documentation/v1/00-readme-old-intro.md` line 12 | `esml/images/esml-project-ticket.png` | likely | 1 | 258.8 KB |
| `esml/z/README.md` line 120 | `esml/images/esml-s01e01-2.png` | likely | 1 | 230.4 KB |
| `esml/z/README.md` line 563 | `esml/images/scoring-batch-or-online.png` | likely | 1 | 184.4 KB |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/21-train_in_2_gold_train_pipeline.py` line 34 | `esml/common/baselayer_azure_ml_pipeline.py` | likely | 1 | 134.1 KB |
| `documentation/v1/02-install_notes_more_info.md` line 40 | `esml/images/mlops-release-gate.png` | likely | 1 | 126.8 KB |
| `documentation/v1/00-readme-old-intro.md` line 2 | `esml/images/23_ESML_4_main_components.png` | likely | 1 | 109.6 KB |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/21-bronze_2_gold.py` line 31 | `esml/common/baselayer_azure_ml.py` | likely | 2 | 105.5 KB |
| `documentation/v2/40-49/42-FAQ-01.md` line 39 | `esml/images/mlops-env-arg.png` | likely | 1 | 96.7 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 36 | `environment_setup/aifactory/bicep/scripts/preflight.sh` | likely | 2 | 85.5 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 414 | `environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v2.bicep` | likely | 18 | 79.0 KB |
| `documentation/architecture/agents/MCP-Boundary.md` line 126 | `mcp/deploy/rollout.py` | likely | 19 | 78.3 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 10 | `healthmodel/bicep/main.bicep` | likely | 4 | 76.4 KB |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/old/notebook_templates_esml_v13_2019-2022_aml_v126/all/esml_1_howto_configure_model.ipynb` line 194 | `esml/images/01_setup_model_5.png` | likely | 1 | 69.1 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 6 | `healthmodel/src/aifactory_healthmodel/bootstrap.py` | likely | 10 | 64.7 KB |
| `documentation/architecture/infrastructure/AI-Gateway-APIM-Provisioning.md` line 5 | `environment_setup/aifactory/bicep/scripts/apim-gateway-deployment.py` | likely | 1 | 59.5 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 8 | `healthmodel/src/aifactory_healthmodel/domain/definitions.py` | likely | 9 | 58.2 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 24 | `environment_setup/aifactory/bicep/scripts/genDynamicNetworkParamFile.ps1` | likely | 3 | 57.5 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 33 | `environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py` | likely | 1 | 48.5 KB |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/old/notebook_templates_esml_v13_2019-2022_aml_v126/all/esml_1_howto_configure_model.ipynb` line 193 | `esml/images/01_setup_model_4.png` | likely | 1 | 45.7 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 35 | `environment_setup/aifactory/bicep/scripts/deploy-capacity-resource.py` | likely | 1 | 45.2 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 34 | `environment_setup/aifactory/bicep/scripts/dashboard_usage.py` | likely | 1 | 44.1 KB |
| `documentation/architecture/pipelines/Lifecycle-and-Recovery.md` line 13 | `environment_setup/aifactory/bicep/scripts/project-deletion.py` | likely | 1 | 43.3 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 7 | `healthmodel/src/aifactory_healthmodel/application/service.py` | likely | 10 | 43.1 KB |
| `documentation/v2/30-39/32-dashboards.md` line 852 | `environment_setup/aifactory/bicep/scripts/deploy-dashboards-only.py` | likely | 1 | 42.7 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-healthmodel.yaml` line 109 | `healthmodel/aif_healthmodel.py` | likely | 6 | 40.0 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 13 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/factory_api.py` | likely | 5 | 35.3 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 21 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/composition.py` | likely | 7 | 35.3 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 47 | `environment_setup/aifactory/bicep/modules/csFoundry/aiFoundry2025AvmOff.bicep` | likely | 2 | 34.1 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 23 | `environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1` | likely | 1 | 29.2 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 31 | `environment_setup/aifactory/bicep/scripts/delete-caphost-and-foundry-and-its-subnet.sh` | likely | 1 | 28.2 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 7 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/service.py` | likely | 2 | 26.9 KB |
| `environment_setup/unit-tests/test-bicep/docs/generator/VisualGuide.csproj` line 13 | `environment_setup/unit-tests/test-bicep/docs/generator/guide.template.html` | likely | 1 | 26.4 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 115 | `environment_setup/aifactory/bicep/scripts/delete-subnets-for-projects.sh` | likely | 1 | 19.8 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 40 | `environment_setup/aifactory/bicep/scripts/cleanup-project-orphan-roles.py` | likely | 1 | 19.8 KB |
| `environment_setup/aifactory/bicep/esml-util/29-create-sp-or-update-oid-for-project.sh` line 168 | `environment_setup/aifactory/bicep/esml-util/images/sp-aifactory-house.png` | likely | 1 | 18.3 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 12 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/operation.py` | likely | 1 | 18.2 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 23 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep` | likely | 2 | 16.1 KB |
| `documentation/architecture/infrastructure/AI-Gateway-APIM-Provisioning.md` line 6 | `environment_setup/aifactory/bicep/scripts/apim_gateway_config.py` | likely | 1 | 15.7 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 37 | `environment_setup/aifactory/bicep/scripts/region_report.py` | likely | 1 | 14.1 KB |
| `documentation/v2/30-39/33-install-azureml-sdk-v1+v2.md` line 6 | `environment_setup/install_sdk/user_dev_env_install/AzureML_v1_55_and_v2_1_15.zip` | likely | 1 | 14.0 KB |
| `documentation/architecture/infrastructure/Identity-and-Personas.md` line 17 | `environment_setup/aifactory/bicep/scripts/kv_principal_object_ids.py` | likely | 1 | 13.6 KB |
| `documentation/v2/10-19/10-factory-onion-architecture.md` line 95 | `environment_setup/aifactory/bicep/scripts/prepareSeedingKeyVaultPrivateDns.ps1` | likely | 1 | 13.5 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5813 | `environment_setup/aifactory/bicep/scripts/generate_hosts_file_info.py` | likely | 1 | 13.2 KB |
| `environment_setup/aifactory/bicep/esml-util/28-policy.bicep` line 50 | `environment_setup/aifactory/bicep/esml-util/policy/Deploy-VNET-HubSpoke.json` | likely | 1 | 12.9 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 38 | `environment_setup/aifactory/bicep/esml-genai-1/03b-ai-search.bicep` | likely | 2 | 12.4 KB |
| `documentation/v2/30-39/32-dashboards.md` line 736 | `environment_setup/aifactory/bicep/modules/workbooks/my-project/usage.kql` | likely | 1 | 12.0 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 377 | `environment_setup/aifactory/bicep/scripts/deploy-integration-with-retry.py` | likely | 1 | 11.1 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 28 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-factory-api-host.ps1` | likely | 1 | 11.1 KB |
| `documentation/v2/20-29/25-personas-aifactory.md` line 17 | `environment_setup/aifactory/bicep/scripts/Invoke-ProjectLakeAccess.ps1` | likely | 1 | 11.0 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 6 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/http_api.py` | likely | 3 | 10.8 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5870 | `environment_setup/aifactory/bicep/scripts/ado/74_Cleanup_CapabilityHosts.sh` | likely | 1 | 10.5 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/RUNBOOK.md` line 67 | `environment_setup/aifactory/bicep/scripts/ado/124_send_email_notifications.sh` | likely | 1 | 10.4 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 15 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/sdk_backend.py` | likely | 1 | 10.0 KB |
| `environment_setup/aifactory/bicep/modules/myProjectWorkbook.bicep` line 54 | `environment_setup/aifactory/bicep/modules/workbooks/my-project/tokens.kql` | likely | 1 | 9.1 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 18 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/runner_protocol.py` | likely | 1 | 9.0 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 22 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/settings.py` | likely | 1 | 8.9 KB |
| `documentation/v2/30-39/32-dashboards.md` line 737 | `environment_setup/aifactory/bicep/modules/workbooks/my-project/cost.kql` | likely | 1 | 8.7 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 16 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/trackers.py` | likely | 2 | 8.7 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 14 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/rest_backend.py` | likely | 1 | 8.5 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 116 | `environment_setup/aifactory/bicep/scripts/ado/71_If_Error_AIFoundryHubAndProject_DeleteIt.sh` | likely | 1 | 8.5 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 19 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/runner.py` | likely | 1 | 7.7 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5890 | `environment_setup/aifactory/bicep/scripts/ado/72_If_Error_AIServices_DeleteIt.sh` | likely | 1 | 7.7 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 3567 | `environment_setup/aifactory/bicep/esml-genai-1/05b-container-apps.bicep` | likely | 1 | 7.5 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5900 | `environment_setup/aifactory/bicep/scripts/ado/73_If_Error_AIFoundryProject_DeleteIt.sh` | likely | 1 | 7.2 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/aifactory-governance/jobs/job-cross-charging.yaml` line 78 | `environment_setup/aifactory/bicep/scripts/ado/122_collect_cost_data.sh` | likely | 1 | 7.2 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 1973 | `environment_setup/aifactory/bicep/scripts/delete-capHost-command.sh` | likely | 1 | 7.1 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 3452 | `environment_setup/aifactory/bicep/esml-genai-1/04b-postgresql.bicep` | likely | 1 | 7.0 KB |
| `documentation/architecture/infrastructure/Compute-Security-Baseline.md` line 10 | `environment_setup/aifactory/bicep/esml-common/modules-common/avdSessionHost.bicep` | likely | 1 | 6.9 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/aifactory-governance/jobs/job-cross-charging.yaml` line 86 | `environment_setup/aifactory/bicep/scripts/ado/123_upload_to_datalake.sh` | likely | 1 | 6.7 KB |
| `documentation/architecture/infrastructure/Compute-Security-Baseline.md` line 9 | `environment_setup/aifactory/bicep/modules/virtualMachinePublic.bicep` | likely | 1 | 6.7 KB |
| `documentation/v2/30-39/37-mlops.md` line 413 | `healthmodel/definitions/project.json` | likely | 2 | 6.4 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 11 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/ids.py` | likely | 1 | 6.2 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 8 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/planner.py` | likely | 1 | 6.2 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 3672 | `environment_setup/aifactory/bicep/scripts/discover-aml-aks-attachment.py` | likely | 1 | 6.1 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5910 | `environment_setup/aifactory/bicep/scripts/ado/79_Purge_If_SoftDeleted_71_72_After5minutes.sh` | likely | 1 | 5.8 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 20 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/ports.py` | likely | 1 | 5.2 KB |
| `environment_setup/aifactory/bicep/esml-util/26-add-esml-project-member.ps1` line 122 | `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnetRGs.bicep` | likely | 1 | 5.1 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 17 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/runner_backend.py` | likely | 2 | 5.1 KB |

43 more rows are not shown; plan.json has all of them.

## References that could not be resolved

| File | Line | Reference text | Why |
|---|---:|---|---|
| `00-start.sh` | 37 | `/dev/null` | not found in the repository |
| `00-start.sh` | 39 | `/dev/null` | not found in the repository |
| `00-start.sh` | 41 | `/dev/null` | not found in the repository |
| `01-start-v125-and-above.sh` | 7 | `/dev/null` | not found in the repository |
| `01-start-v125-and-above.sh` | 9 | `/dev/null` | not found in the repository |
| `01-start-v125-and-above.sh` | 11 | `/dev/null` | not found in the repository |
| `README.md` | 54 | `./usecase_code/50-ml-factory/readme.md` | not found in the repository |
| `README.md` | 132 | `./usecase_code/50-ml-factory/readme.md` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 52 | `/dev/null` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 54 | `/dev/null` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 56 | `/dev/null` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 78 | `azurefactory-cli/src/azurefactory` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 79 | `azurefactory-cli/tests` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 86 | `install_config_wizard/api-usage-examples/requests` | not found in the repository |
| `bootstrap/01-aif-copy-aifactory-templates.sh` | 87 | `install_config_wizard/api-usage-examples/tests` | not found in the repository |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | 247 | `/dev/null` | not found in the repository |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | 249 | `/dev/null` | not found in the repository |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | 251 | `/dev/null` | not found in the repository |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | 900 | `azure-enterprise-scale-ml/00-start.sh` | not found in the repository |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | 904 | `03-ADO-YAML-bootstrap-files-no-var-overwrite.sh` | not found in the repository |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | 257 | `/dev/null` | not found in the repository |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | 259 | `/dev/null` | not found in the repository |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | 261 | `/dev/null` | not found in the repository |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | 337 | `azure-enterprise-scale-ml/00-start.sh` | not found in the repository |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | 341 | `03-GH-bootstrap-files-no-env-overwrite.sh` | not found in the repository |
| `bootstrap/GH-update-aifactory-and-run-project.sh` | 680 | `10-GH-create-or-update-github-variables.sh` | not found in the repository |
| `bootstrap/azurefactory.sh` | 15 | `/dev/null` | not found in the repository |
| `bootstrap/azurefactory.sh` | 17 | `/dev/null` | not found in the repository |
| `bootstrap/azurefactory.sh` | 19 | `/dev/null` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 170 | `/dev/null` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 172 | `/dev/null` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 174 | `/dev/null` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 1564 | `./01-aif-copy-aifactory-templates.sh` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 1605 | `./03-ADO-YAML-bootstrap-files-no-var-overwrite.sh` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 1609 | `./03-GH-bootstrap-files-no-env-overwrite.sh` | not found in the repository |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` | 3321 | `./10-GH-create-or-update-github-variables.sh` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 53 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 54 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 55 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 76 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 77 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 78 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 109 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 111 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 113 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 141 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 142 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 143 | `/dev/null` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 309 | `!/lib/` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 310 | `/lib/*` | the pattern matches no file |
| `bootstrap/lib/layout_router.sh` | 316 | `!/ui/` | not found in the repository |
| `bootstrap/lib/layout_router.sh` | 317 | `/ui/*` | a computed path with too little fixed text to follow |
| `bootstrap/lib/layout_router.sh` | 318 | `!/ui/terminal.sh` | not found in the repository |
| `bootstrap/lib/registered_creation.py` | 130 | `../.azurefactory-tools` | not found in the repository |
| `bootstrap/lib/registered_personas.py` | 59 | `../azure-enterprise-scale-ml` | not found in the repository |
| `bootstrap/lib/registered_personas.py` | 62 | `../.azurefactory-tools/persona-engine` | not found in the repository |
| `bootstrap/lib/release_version.py` | 188 | `../../.git` | not found in the repository |
| `bootstrap/lib/release_version.py` | 189 | `../../.git` | not found in the repository |
| `bootstrap/lib/release_version.sh` | 13 | `/dev/null` | not found in the repository |
| `bootstrap/lib/release_version.sh` | 15 | `/dev/null` | not found in the repository |
| `bootstrap/lib/runner-prerequisites.sh` | 297 | `/etc/os-release` | not found in the repository |
| `bootstrap/lib/runner-registration.ps1` | 202 | `./config.cmd` | not found in the repository |
| `bootstrap/lib/runner-registration.sh` | 303 | `/etc/os-release` | not found in the repository |
| `bootstrap/lib/runner-registration.sh` | 342 | `/dev/stdin` | not found in the repository |
| `bootstrap/python-sdk/aifactory_sdk.py` | 24 | `azure-enterprise-scale-ml/environment_setup/install_config_wizard/api-usage-examples/python/*` | the pattern matches no file |
| `bootstrap/python-sdk/aifactory_sdk.py` | 26 | `azure-enterprise-scale-ml/environment_setup/install_config_wizard/api-usage-examples/python/*` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/10-get_environment.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/10-get_environment.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/21-train_in_2_gold_train_pipeline.py` | 29 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/21-train_in_2_gold_train_pipeline.py` | 31 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/31-deploy_and_smoketest_batch_scoring.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/32-deploy_online_aks.py` | 31 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/01_template_v14/32-smoke_test_online.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/scripts/ci.py` | 182 | `azure.core.exceptions` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/scripts/ci.py` | 235 | `azure.core.exceptions` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 64 | `.ci-test-*` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 253 | `.core-test-*` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 270 | `.core-test-*/runtime.json` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 270 | `.core-test-*/scenario.json` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 280 | `.core-test-*/bundle` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 282 | `.core-test-*/bundle/pipeline.yml` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 283 | `.core-test-*/bundle/manifest.json` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 295 | `.bootstrap-test-*` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 336 | `../ml-environment/outputs` | not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | 338 | `../ml-environment/outputs/deploy` | not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_selection_ci.py` | 25 | `.selection-ci-*` | the pattern matches no file |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/10-get_environment.py` | 35 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/10-get_environment.py` | 36 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/21-bronze_2_gold.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/21-bronze_2_gold.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/22-train_automl.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/22-train_automl.py` | 29 | `azureml.train.automl` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/22-train_automl.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/23-compare_scoring_register.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/23-compare_scoring_register.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/31-deploy_online_aks.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/31-deploy_online_aks.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/31-test_online_aks.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/31-test_online_aks.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/40-deploy_batch_aml.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/40-deploy_batch_aml.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/40-test_batch_aml.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m03/40-test_batch_aml.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/10-get_environment.py` | 35 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/10-get_environment.py` | 36 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/21-bronze_2_gold_local.py` | 29 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/21-bronze_2_gold_local.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/21-bronze_2_gold_pipeline.py` | 29 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/21-bronze_2_gold_pipeline.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_automl.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_automl.py` | 29 | `azureml.train.automl` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_automl.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_manual_pipeline.py` | 29 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/22-train_manual_pipeline.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/23-compare_scoring_register.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/23-compare_scoring_register.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/31-deploy_online_aks.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/31-deploy_online_aks.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/31-test_online_aks.py` | 28 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/31-test_online_aks.py` | 29 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/40-deploy_batch_aml.py` | 29 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/40-deploy_batch_aml.py` | 30 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/40-deploy_batch_aml.py` | 35 | `azureml.core.dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/40-deploy_batch_aml.py` | 36 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/mlops/old/demo_project02_m12_remote/40-deploy_batch_aml.py` | 37 | `azureml.pipeline.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/score.py` | 12 | `azureml.automl.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/score.py` | 13 | `azureml.automl.core.shared` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/score.py` | 14 | `azureml.telemetry` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/00_esmladmin_scripts/1_Lake_init_mount.py` | 17 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/00_esmladmin_scripts/1_Lake_init_mount.py` | 18 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 13 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 14 | `azureml.core.dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 15 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 16 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 17 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 18 | `azureml.core.model` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 19 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 23 | `pipelines.M11.esmlrt.interfaces.iESMLController` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/ESMLDatabricksController.py` | 24 | `pipelines.M11.esmlrt.runtime.ESMLController` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/azure_functions.py` | 51 | `azureml.core.workspace` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/azure_functions.py` | 52 | `azureml.core.authentication` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/azure_functions.py` | 95 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/common/azure_functions.py` | 112 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/21_split_GOLD_and_register_datasets.py` | 202 | `azureml.core.dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/21_split_GOLD_and_register_datasets.py` | 209 | `azureml.core.dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_scoring_gold.py` | 6 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_scoring_gold.py` | 8 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_scoring_gold.py` | 9 | `pipelines.M11.esmlrt.interfaces.iESMLController` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_scoring_gold.py` | 137 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_code/your_train_code.py` | 15 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_register.py` | 19 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_register.py` | 171 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_register.py` | 212 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_register.py` | 452 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/01_your_model_placeholder/M01/30_train_register.py` | 453 | `azureml.core.resource_configuration` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/21_split_GOLD_and_register_datasets.py` | 202 | `azureml.core.dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/21_split_GOLD_and_register_datasets.py` | 209 | `azureml.core.dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_scoring_gold.py` | 6 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_scoring_gold.py` | 8 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_scoring_gold.py` | 9 | `pipelines.M11.esmlrt.interfaces.iESMLController` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_scoring_gold.py` | 137 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_code/your_train_code.py` | 15 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_register.py` | 19 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_register.py` | 171 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_register.py` | 212 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_register.py` | 452 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_databricks/esml/dev/project/11_diabetes_model_reg/M11/30_train_register.py` | 453 | `azureml.core.resource_configuration` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/in2silver.py` | 1 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/in2silver.py` | 2 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/scoring_gold.py` | 5 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/scoring_gold.py` | 6 | `azureml.data.dataset_factory` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/scoring_gold.py` | 7 | `azureml.core.model` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/silver_merged_2_gold.py` | 6 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/silver_merged_2_gold.py` | 7 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/silver_merged_2_gold.py` | 8 | `azureml.data.file_dataset` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/silver_merged_2_gold.py` | 9 | `azureml.data.dataset_factory` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_manual.py` | 4 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_manual.py` | 5 | `azureml.data.dataset_factory` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_manual.py` | 16 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 4 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 5 | `azureml.data.dataset_factory` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 16 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 18 | `azureml.core.run` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 19 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 20 | `azureml.pipeline.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 21 | `azureml.core.model` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_post_automl_step.py` | 23 | `azureml.train.automl.run` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_split_and_register.py` | 4 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_split_and_register.py` | 5 | `azureml.data.dataset_factory` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/train_split_and_register.py` | 7 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/your_code/your_scoring_file_v_1_0_0.py` | 9 | `azureml.automl.core.shared` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/your_code/your_train_code.py` | 14 | `azureml.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_defaults/pipeline_template/your_code/your_train_code.py` | 25 | `azureml.train.automl` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_custom.py` | 12 | `azureml.automl.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_custom.py` | 13 | `azureml.automl.core.shared` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_custom.py` | 14 | `azureml.telemetry` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_dev.py` | 12 | `azureml.automl.core` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_dev.py` | 13 | `azureml.automl.core.shared` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_dev.py` | 14 | `azureml.telemetry` | module not found in the repository |
| `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl/scoring_file_dev_M01_titanic.py` | 12 | `azureml.automl.core` | module not found in the repository |

819 more rows are not shown; plan.json has all of them.

## Tests and docs (followers)

A follower stays when what it belongs to stays. It never keeps code alive.

| Group | Kept | Dropped |
|---|---:|---:|
| docs | 218 | 1 |
| repository | 7 | 0 |
| tests | 286 | 0 |

## Submodule links and symlinks

None.

## Verification

The verify commands have not been run on this plan.

## Warnings

- keep: 'RELEASE_126.md' matches no file
- drop: '**/previous-release/**' matches no file
- drop: 'environment_setup/install_tutorial_guide/old/**' matches no file
- drop: 'environment_setup/install_config_wizard/maui/*.cab' matches no file
- drop: 'environment_setup/install_config_wizard/maui/*.msi' matches no file
- drop: 'environment_setup/install_tutorial_guide/*.cab' matches no file
- drop: 'environment_setup/install_tutorial_guide/*.msi' matches no file

## Broken references in the compacted tree

None.

## Restore a file

Every dropped file is still in the base commit:

```
git checkout c8ab933fb1ea58ae799e962bc21d568a154745df -- <path>
```
