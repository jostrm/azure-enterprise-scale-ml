# Compaction report

This branch was made by compact-repo. It holds what the entry points use; everything else was removed in one commit.

| Item | Value |
|---|---|
| Base commit | `550e8f4a9e848ffcfa782b59fe9bb1410032d633` |
| Target branch | `release/v1.26` |
| Profile hash | `a252e4946e8b0daad55aaf01f90b07a824c67b4a92d80e0a65a30877319fae87` |
| Tool | compact-repo 0.1.0 |

## Summary

|  | Files | Size |
|---|---:|---:|
| Before | 3,031 | 294.6 MB (308,861,201 bytes) |
| Kept | 2,694 | 281.0 MB (294,659,833 bytes) |
| Dropped (saved) | 337 | 13.5 MB (14,201,368 bytes) |

### By class

| Class | Files | Size | Kept | Dropped |
|---|---:|---:|---:|---:|
| root | 883 | 9.9 MB | 883 | 0 |
| pinned | 744 | 82.4 MB | 744 | 0 |
| dependency | 571 | 147.1 MB | 571 | 0 |
| follower | 494 | 41.4 MB | 494 | 0 |
| report | 2 | 143.2 KB | 2 | 0 |
| forced-drop | 337 | 13.5 MB | 0 | 337 |

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
| `RELEASE_126.md` | kept by the profile (keep: RELEASE_126.md) |
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
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/.gitignore` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/copy.example.json` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/job-payload.example.json` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/main.bicep` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/parameters.example.json` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/prepare_run.py` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/readme.md` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/tests/test_templates.py` | entry point: ML Model Factory data-ops template; accelerator/tests/test_orchestration_matrix.py and test_storage_selection.py read it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/.gitignore` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/ado/ml-factory.yml` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/ado/readme.md` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/github/ml-factory.yml` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/github/readme.md` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/readme.md` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/scripts/bootstrap.py` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/scripts/ci.py` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_ci.py` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests/test_selection_ci.py` | entry point: ML Model Factory MLOps template for Azure DevOps and GitHub; accelerator/tests/test_orchestration_matrix.py reads it. |
| `documentation/architecture/.gitignore` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/Index.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/agents/Agent-Factory.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/agents/Chat-and-Grounding.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/agents/MCP-Boundary.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/architecture/Evidence-and-Gaps.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/architecture/Factory-Scope-Model.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/architecture/Repository-Boundaries.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/architecture/System-Context.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/contracts/Factory-API-and-SDK.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/contracts/Lifecycle-Function.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/contracts/Packaging-and-Release.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/contracts/Reviewed-Operations.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/contracts/dual-graph-lifecycle.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/decisions/ADR-001-Dual-Graph.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/governance/Trust-and-Authorization.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/infrastructure/AI-Gateway-APIM-Provisioning.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/infrastructure/Bootstrap-and-Layouts.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/infrastructure/Compute-Security-Baseline.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/infrastructure/Health-Models.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/infrastructure/Identity-and-Personas.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/lineage/Lake-and-Data-Lineage.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/lineage/Retrieval-Provenance.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/ml-lifecycle/Engines-and-Pipelines.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/ml-lifecycle/Monitoring-and-Retraining.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/ml-lifecycle/Selection-and-Promotion.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/patterns/Dependency-Injection.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/patterns/State-Machines-and-DAGs.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/pipelines/Lifecycle-and-Recovery.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/architecture/pipelines/Orchestration-and-Updates.md` | kept by the profile (keep: documentation/architecture/**) |
| `documentation/readme.md` | kept by the profile (keep: documentation/readme.md) |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/10-factory-onion-architecture-v2.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/10-factory-onion-architecture.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/11-architecture-diagrams.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/12-permissions-users-ad-sps.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/12-prerequisites-setup.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/12-resourceproviders.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/12-seeding-keyvault.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/13-flow-diagram-1.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/13-flow-diagram-dataops.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/13-parameters-ado.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/13-setup-aifactory-gha.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/13-setup-aifactory.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/14-networking-privateDNS.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/15-aifactory-overview.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/16-ad-groups-personas.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/17-cli-and-api-and-usage.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/18-cli-and-api-and-usage.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/19-cli-and-api-and-usage.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/20-cli-and-api-and-usage.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/21-agent-factory-chat.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/22-lifecycle-azure-function.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/_13-setup-aifactory.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/aifactory-parameters-v122.md` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/esaf-architecture-own-hub.svg` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-aifactory-4-components-2024-small.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture-animated.svg` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture-v2-animated.svg` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture-v2.gif` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture-v2.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture-v2.svg` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture.gif` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-factory-onion-architecture.svg` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-mlops-genaiops.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-personas-2-processes.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-two-architectures-v2-small.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/10-two-architectures-v2.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-architecture-detailed-llmops.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-architecture-detailed-mlops.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-architecture-highlevel-esml-services-integration.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-architecture-ragchat-scaling.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-services-common-projects.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-services-highlevel-esgenai.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-services-highlevel-esml.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-services-highlevel-esml_.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/11-services-highlevel-esml_fabric.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-datalake-permissions-in-out-bad.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-datalake-permissions-projects.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-datalake-permissions-root.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-keyvault-project-permissions.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-network-custom-dns.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-prerequisites-ado-agent-win2019.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-prerequisites-ado-agent.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-prerequisites-ado-import-release-pipeline.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-prerequisites-ado-import-tasks.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-prerequisites-ado-select-arm-con.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-prerequisites-aml-sp-oid.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/12-seeding-keyvault-secrets.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/13-flowdiagram-add-project-esml.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/13-flowdiagram-add-user-esml.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/13-setup-aifactory-ado-add-artifact.png` | kept by the profile (keep: documentation/v2/**) |
| `documentation/v2/10-19/images/13-setup-aifactory-ado-arm-new-service-con-dialog.png` | kept by the profile (keep: documentation/v2/**) |

1,427 more rows are not shown; plan.json has all of them.

## Largest dropped files

| File | Size | Reason |
|---|---:|---|
| `esml/images/esml-s01e01-0.png` | 1.2 MB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-autolake.png` | 1.1 MB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-turnkey.png` | 1.0 MB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-oneslider.png` | 909.6 KB | dropped by the profile (drop: esml/**) |
| `esml/images/scoring-lake.png` | 764.3 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-get-scoring.png` | 736.3 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-s02e01-4steps.png` | 630.0 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-s01e01-1.png` | 569.1 KB | dropped by the profile (drop: esml/**) |
| `esml/images/Bicep-1-click.png` | 402.4 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-autolake-meta.png` | 275.1 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-arch-small.png` | 272.3 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-project-ticket.png` | 258.8 KB | dropped by the profile (drop: esml/**) |
| `esml/images/esml-s01e01-2.png` | 230.4 KB | dropped by the profile (drop: esml/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_templates_esml_v14_2022-06-2023_aml_v143/00_v143_esml_ml_features.ipynb` | 184.5 KB | dropped by the profile (drop: copy_my_subfolders_to_my_grandparent/notebook_templates/**) |
| `esml/images/scoring-batch-or-online.png` | 184.4 KB | dropped by the profile (drop: esml/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/notebook_templates_esml_v14_2022-06-2023_aml_v143/M10_v143_esml_classification_1_train_env_dev.ipynb` | 168.1 KB | dropped by the profile (drop: copy_my_subfolders_to_my_grandparent/notebook_templates/**) |
| `copy_my_subfolders_to_my_grandparent/dbx/esml_v14_aml_v145.dbc` | 157.7 KB | dropped by the profile (drop: copy_my_subfolders_to_my_grandparent/dbx/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/old/notebook_templates_esml_v13_2019-2022_aml_v126/all/esml_classification_1_train_env_dev.ipynb` | 143.3 KB | dropped by the profile (drop: copy_my_subfolders_to_my_grandparent/notebook_templates/**) |
| `esml/common/baselayer_azure_ml_pipeline.py` | 134.1 KB | dropped by the profile (drop: esml/**) |
| `copy_my_subfolders_to_my_grandparent/notebook_templates/1_quickstart/1b_R&D_TRAIN_M00.ipynb` | 130.2 KB | dropped by the profile (drop: copy_my_subfolders_to_my_grandparent/notebook_templates/**) |

## Dropped by top-level folder

| Folder | Files | Size |
|---|---:|---:|
| `esml/` | 25 | 9.1 MB |
| `copy_my_subfolders_to_my_grandparent/` | 200 | 4.0 MB |
| `environment_setup/` | 84 | 194.4 KB |
| `esmlrt/` | 16 | 138.2 KB |
| `documentation/` | 9 | 54.7 KB |
| `usecase_code/` | 1 | 4.8 KB |
| `esmlfac/` | 2 | 1.9 KB |

## Kept only by weak evidence

These files are kept because of a path string, a pattern, or a folder that is used as a whole. If such a reference does not really need them, add them to `drop` in the profile.

| Reference | Target | Confidence | Files kept only through it | Size |
|---|---|---|---:|---:|
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/region-report-steps.yaml` line 17 | `**/*.json` | dynamic | 17 | 95.1 MB |
| `bootstrap/01-aif-copy-aifactory-templates.sh` line 66 | `environment_setup/aifactory/` | dynamic | 33 | 3.3 MB |
| `environment_setup/azurefactory-cli/tests/test_documentation_site.py` line 244 | `usecase_code/` | dynamic | 21 | 113.3 KB |
| `00-start.sh` line 25 | `bootstrap/` | dynamic | 2 | 14.3 KB |
| `environment_setup/unit-tests/test-bicep/azure-pipelines.yml` line 69 | `healthmodel/bicep/` | dynamic | 2 | 4.4 KB |
| `bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh` line 28 | `**/.env.template` | dynamic | 1 | 2.6 KB |
| `bootstrap/lib/create-new-aifactory-scaleset.sh` line 3652 | `**/agents.json` | dynamic | 1 | 2.1 KB |
| `bootstrap/lib/runner_bootstrap.py` line 379 | `[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*` | dynamic | 2 | 1.5 KB |
| `usecase_code/50-ml-model-factory/accelerator/tests/test_orchestration_matrix.py` line 39 | `copy_my_subfolders_to_my_grandparent/` | dynamic | 1 | 1.1 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md` line 99 | `environment_setup/install_config_wizard/windows/aifactory-config-windows.zip` | likely | 1 | 43.1 MB |
| `documentation/architecture/infrastructure/Compute-Security-Baseline.md` line 21 | `environment_setup/unit-tests/test-bicep/unit/test_defender_compute_baseline.py` | likely | 2 | 1.3 MB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 36 | `environment_setup/aifactory/bicep/scripts/preflight.sh` | likely | 2 | 85.5 KB |
| `RELEASE_126.md` line 226 | `healthmodel/bicep/main.bicep` | likely | 2 | 74.5 KB |
| `documentation/architecture/agents/MCP-Boundary.md` line 126 | `mcp/deploy/rollout.py` | likely | 15 | 66.9 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 6 | `healthmodel/src/aifactory_healthmodel/bootstrap.py` | likely | 10 | 64.7 KB |
| `RELEASE_126.md` line 174 | `environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v3.bicep` | likely | 1 | 64.0 KB |
| `documentation/architecture/infrastructure/AI-Gateway-APIM-Provisioning.md` line 5 | `environment_setup/aifactory/bicep/scripts/apim-gateway-deployment.py` | likely | 1 | 59.5 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 8 | `healthmodel/src/aifactory_healthmodel/domain/definitions.py` | likely | 9 | 58.2 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 24 | `environment_setup/aifactory/bicep/scripts/genDynamicNetworkParamFile.ps1` | likely | 3 | 57.5 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 33 | `environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py` | likely | 1 | 48.5 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 35 | `environment_setup/aifactory/bicep/scripts/deploy-capacity-resource.py` | likely | 1 | 45.2 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 34 | `environment_setup/aifactory/bicep/scripts/dashboard_usage.py` | likely | 1 | 44.1 KB |
| `documentation/architecture/pipelines/Lifecycle-and-Recovery.md` line 13 | `environment_setup/aifactory/bicep/scripts/project-deletion.py` | likely | 1 | 43.3 KB |
| `documentation/architecture/infrastructure/Health-Models.md` line 7 | `healthmodel/src/aifactory_healthmodel/application/service.py` | likely | 10 | 43.1 KB |
| `documentation/v2/30-39/32-dashboards.md` line 852 | `environment_setup/aifactory/bicep/scripts/deploy-dashboards-only.py` | likely | 1 | 42.7 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-healthmodel.yaml` line 109 | `healthmodel/aif_healthmodel.py` | likely | 6 | 40.0 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 13 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/factory_api.py` | likely | 5 | 35.3 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 21 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/composition.py` | likely | 7 | 35.3 KB |
| `RELEASE_126.md` line 193 | `environment_setup/aifactory/bicep/modules/csFoundry/aiFoundry2025AvmOff.bicep` | likely | 1 | 32.5 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 23 | `environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1` | likely | 1 | 29.2 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 31 | `environment_setup/aifactory/bicep/scripts/delete-caphost-and-foundry-and-its-subnet.sh` | likely | 1 | 28.2 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 7 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/service.py` | likely | 2 | 26.9 KB |
| `environment_setup/unit-tests/test-bicep/docs/generator/VisualGuide.csproj` line 13 | `environment_setup/unit-tests/test-bicep/docs/generator/guide.template.html` | likely | 1 | 26.4 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 115 | `environment_setup/aifactory/bicep/scripts/delete-subnets-for-projects.sh` | likely | 1 | 19.8 KB |
| `documentation/v2/10-19/10-deployment-stack-VS-aifactory-governance.md` line 40 | `environment_setup/aifactory/bicep/scripts/cleanup-project-orphan-roles.py` | likely | 1 | 19.8 KB |
| `RELEASE_126.md` line 195 | `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/main.bicep` | likely | 1 | 19.6 KB |
| `environment_setup/aifactory/bicep/esml-util/29-create-sp-or-update-oid-for-project.sh` line 168 | `environment_setup/aifactory/bicep/esml-util/images/sp-aifactory-house.png` | likely | 1 | 18.3 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 12 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/operation.py` | likely | 1 | 18.2 KB |
| `RELEASE_126.md` line 173 | `environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v2.bicep` | likely | 1 | 17.6 KB |
| `RELEASE_126.md` line 234 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/infra/function-app.bicep` | likely | 2 | 16.1 KB |
| `documentation/architecture/infrastructure/AI-Gateway-APIM-Provisioning.md` line 6 | `environment_setup/aifactory/bicep/scripts/apim_gateway_config.py` | likely | 1 | 15.7 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 37 | `environment_setup/aifactory/bicep/scripts/region_report.py` | likely | 1 | 14.1 KB |
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
| `RELEASE_126.md` line 181 | `environment_setup/aifactory/bicep/esml-util/24-add-aks.bicep` | likely | 1 | 10.5 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5870 | `environment_setup/aifactory/bicep/scripts/ado/74_Cleanup_CapabilityHosts.sh` | likely | 1 | 10.5 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/runbooks/showback/RUNBOOK.md` line 67 | `environment_setup/aifactory/bicep/scripts/ado/124_send_email_notifications.sh` | likely | 1 | 10.4 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 15 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/sdk_backend.py` | likely | 1 | 10.0 KB |
| `RELEASE_126.md` line 208 | `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/private-endpoint-and-dns.bicep` | likely | 1 | 10.0 KB |
| `RELEASE_126.md` line 177 | `environment_setup/aifactory/bicep/esml-project/24-add-aks.bicep` | likely | 1 | 9.8 KB |
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
| `RELEASE_126.md` line 170 | `environment_setup/aifactory/bicep/esml-common/modules-common/avdSessionHost.bicep` | likely | 1 | 6.9 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/aifactory-governance/jobs/job-cross-charging.yaml` line 86 | `environment_setup/aifactory/bicep/scripts/ado/123_upload_to_datalake.sh` | likely | 1 | 6.7 KB |
| `RELEASE_126.md` line 224 | `environment_setup/aifactory/bicep/modules/virtualMachinePublic.bicep` | likely | 1 | 6.7 KB |
| `documentation/v2/30-39/37-mlops.md` line 413 | `healthmodel/definitions/project.json` | likely | 2 | 6.4 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 11 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/domain/ids.py` | likely | 1 | 6.2 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 8 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/planner.py` | likely | 1 | 6.2 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 3672 | `environment_setup/aifactory/bicep/scripts/discover-aml-aks-attachment.py` | likely | 1 | 6.1 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml` line 5910 | `environment_setup/aifactory/bicep/scripts/ado/79_Purge_If_SoftDeleted_71_72_After5minutes.sh` | likely | 1 | 5.8 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 20 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/ports.py` | likely | 1 | 5.2 KB |
| `RELEASE_126.md` line 230 | `mcp/infra/modules/application.bicep` | likely | 1 | 5.1 KB |
| `RELEASE_126.md` line 189 | `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnetRGs.bicep` | likely | 1 | 5.1 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 17 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/adapters/runner_backend.py` | likely | 2 | 5.1 KB |
| `RELEASE_126.md` line 209 | `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/standard-dependent-resources.bicep` | likely | 1 | 5.1 KB |
| `RELEASE_126.md` line 229 | `mcp/infra/main.bicep` | likely | 2 | 5.0 KB |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/aifactory-governance/jobs/job-cross-charging.yaml` line 70 | `environment_setup/aifactory/bicep/scripts/ado/121_discover_resource_groups.sh` | likely | 1 | 4.7 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 26 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-ops.yml` | likely | 1 | 4.6 KB |
| `documentation/architecture/infrastructure/IaC-and-Private-Networking.md` line 26 | `environment_setup/aifactory/bicep/scripts/modules/logicAppSubnet.ps1` | likely | 1 | 4.4 KB |
| `RELEASE_126.md` line 186 | `environment_setup/aifactory/bicep/modules/addUserAsCoreteamBYOVnet.bicep` | likely | 1 | 4.4 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 27 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/scripts/install-lifecycle-runner.ps1` | likely | 1 | 4.3 KB |
| `RELEASE_126.md` line 211 | `environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/validate-existing-resources.bicep` | likely | 1 | 4.2 KB |
| `RELEASE_126.md` line 188 | `environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnet.bicep` | likely | 1 | 4.2 KB |
| `RELEASE_126.md` line 194 | `environment_setup/aifactory/bicep/modules/csFoundry/cs.bicep` | likely | 1 | 4.1 KB |
| another repository | referenced by jostrm/azure-aifactory-config, template-files/creation-workflow/bootstrap/lib/create-new-aifactory-scaleset.sh, line 1603 | likely | 1 | 4.1 KB |
| `RELEASE_126.md` line 171 | `environment_setup/aifactory/bicep/esml-common/modules-common/cloudflareTunnelVm.bicep` | likely | 1 | 4.1 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 5 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/function_app.py` | likely | 1 | 4.0 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 24 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/workflows/aif-event-relay.yml` | likely | 1 | 3.9 KB |
| `RELEASE_126.md` line 176 | `environment_setup/aifactory/bicep/esml-project/23-add-dsvm.bicep` | likely | 1 | 3.9 KB |
| `documentation/architecture/contracts/Lifecycle-Function.md` line 9 | `usecase_code/10-azure-function/12_func_aifactory_lifecycle/aif_lifecycle/application/resolver.py` | likely | 2 | 3.7 KB |

54 more rows are not shown; plan.json has all of them.

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
| `documentation/gh-io/docs/architectures.md` | 11 | `reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/architectures.md` | 124 | `reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/architectures.md` | 125 | `setup/02-create-factory.md` | not found in the repository |
| `documentation/gh-io/docs/code-templates/index.md` | 19 | `../usage/index.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/enterprise-scale.md` | 12 | `../setup/add-scale-set.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/enterprise-scale.md` | 61 | `../reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/enterprise-scale.md` | 72 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/index.md` | 58 | `../factory-tools/18-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/intelligence.md` | 25 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/intelligence.md` | 40 | `../factory-tools/20-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/templates/iac.md` | 22 | `../../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/concepts/templates/iac.md` | 44 | `../../setup/05-clean-up.md` | not found in the repository |
| `documentation/gh-io/docs/iac/bicep.md` | 13 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/iac/terraform.md` | 33 | `../setup/05-clean-up.md` | not found in the repository |
| `documentation/gh-io/docs/iac/terraform.md` | 39 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 15 | `setup/index.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 16 | `usage/index.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 21 | `factory-tools/18-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 22 | `project-team/index.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 23 | `factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 24 | `factory-tools/20-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 24 | `setup/05-clean-up.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 25 | `reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 53 | `reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/index.md` | 71 | `setup/05-clean-up.md` | not found in the repository |
| `documentation/gh-io/docs/intelligence.md` | 13 | `factory-tools/20-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/intelligence.md` | 39 | `setup/04-first-agent-chat.md` | not found in the repository |
| `documentation/gh-io/docs/news.md` | 13 | `setup/index.md` | not found in the repository |
| `documentation/gh-io/docs/news.md` | 13 | `usage/index.md` | not found in the repository |
| `documentation/gh-io/docs/news.md` | 15 | `factory-tools/18-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/ado.md` | 8 | `../setup/02-create-factory.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/ado.md` | 9 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/ado.md` | 42 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/ado.md` | 43 | `../factory-tools/20-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/gh.md` | 8 | `../setup/02-create-factory.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/gh.md` | 9 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/orchestrators/gh.md` | 50 | `../factory-tools/20-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/advanced.md` | 8 | `../factory-tools/18-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 9 | `../factory-tools/18-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 14 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 15 | `../factory-tools/20-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 15 | `../setup/05-clean-up.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 40 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 60 | `../reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 64 | `../setup/05-clean-up.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/index.md` | 100 | `../factory-tools/18-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/standard.md` | 10 | `../setup/02-create-factory.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/standard.md` | 74 | `../reference/hub-and-network-modes.md` | not found in the repository |
| `documentation/gh-io/docs/parameters/variables.md` | 7 | `../setup/03-add-project.md` | not found in the repository |
| `documentation/gh-io/docs/resources/index.md` | 25 | `../factory-tools/19-cli-and-api-and-usage.md` | not found in the repository |
| `documentation/gh-io/docs/resources/index.md` | 26 | `../setup/04-first-agent-chat.md` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 7 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/readme.md` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 12 | `../../../../aifactory/parameters/` | points outside the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 13 | `../../../../aifactory/parameters/10-esml-globals-1.json` | points outside the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 19 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-esml.yaml` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 27 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/infra-aifactory-common.json` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 28 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/infra-project-esml.json` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 29 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/infra-project-genai.json` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 30 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/add-coreteam-member.json` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 31 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/infra-project-esml.json` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 32 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/infra-project-genai.json` | not found in the repository |
| `documentation/v2/10-19/12-prereq-ado-create-servicecon-import-ado-pipelines.md` | 36 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/readme.md` | not found in the repository |
| `documentation/v2/10-19/12-resourceproviders.md` | 16 | `../../../../aifactory/esml-util/000-switch-sub2_dev.ps1` | points outside the repository |
| `documentation/v2/10-19/12-resourceproviders.md` | 17 | `../../../../aifactory/esml-util/26-enable-resource-providers.ps1` | points outside the repository |
| `documentation/v2/10-19/13-parameters-ado.md` | 46 | `../../../environment_setup/aifactory/parameters/12-esml-cmn-parameters.json` | not found in the repository |
| `documentation/v2/10-19/13-parameters-ado.md` | 55 | `../../../environment_setup/aifactory/parameters/12-esml-cmn-parameters.json` | not found in the repository |
| `documentation/v2/10-19/13-parameters-ado.md` | 66 | `../../../environment_setup/aifactory/parameters/12-esml-cmn-parameters.json` | not found in the repository |
| `documentation/v2/10-19/13-parameters-ado.md` | 89 | `../../../../aifactory/parameters/` | points outside the repository |
| `documentation/v2/10-19/13-parameters-ado.md` | 89 | `../../../environment_setup/aifactory/parameters/` | not found in the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 52 | `../../../environment_setup/aifactory/parameters/10-esml-globals-4-13_21_22.json` | not found in the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 263 | `../../../environment_setup/aifactory/parameters/12-esml-cmn-parameters.json` | not found in the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 270 | `../../../environment_setup/aifactory/parameters/12-esml-cmn-parameters.json` | not found in the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 281 | `../../../environment_setup/aifactory/parameters/12-esml-cmn-parameters.json` | not found in the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 310 | `../../../../aifactory/parameters/10-esml-globals-4-13_21_22.json` | points outside the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 343 | `../../../../aifactory/esml-util/28-Initiatives.bicep` | points outside the repository |
| `documentation/v2/10-19/14-networking-privateDNS.md` | 346 | `../../../../aifactory/esml-util/28-policy.bicep` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 27 | `../../../../aifactory/esml-infra/azure-devops/bicep/yaml/readme.md` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 28 | `../../../../aifactory/esml-infra/github-actions/bicep/readme.md` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 31 | `../../../../aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 90 | `../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/readme.md` | not found in the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 96 | `../../../../aifactory/esml-infra/azure-devops/bicep/yaml/readme.md` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 97 | `../../../../aifactory/esml-infra/azure-devops/bicep/classic/readme.md` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 98 | `../../../../aifactory/esml-infra/github-actions/bicep/readme.md` | points outside the repository |
| `documentation/v2/10-19/_13-setup-aifactory.md` | 101 | `../../../../aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml` | points outside the repository |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 25 | `artifacts` | not found in the repository |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 32 | `artifacts/text-checks.json` | not found in the repository |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 130 | `artifacts/sample-*.png` | the pattern matches no file |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 145 | `artifacts/*` | the pattern matches no file |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 146 | `artifacts/*` | the pattern matches no file |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 149 | `artifacts/*/timeline.json` | the pattern matches no file |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 151 | `artifacts/*/raster-jobs.json` | the pattern matches no file |
| `documentation/v2/10-19/images/onion/make_onion_raster.py` | 152 | `artifacts/*/raster-jobs.json` | the pattern matches no file |
| `documentation/v2/30-39/31-jumphost-vm-bastion-access.md` | 24 | `./images/31__find_the_NSG.png` | not found in the repository |
| `documentation/v2/30-39/31-jumphost-vm-bastion-access.md` | 27 | `./images/31__click_rule.png` | not found in the repository |
| `documentation/v2/30-39/31-jumphost-vm-bastion-access.md` | 60 | `./images/project_keuvault_shortcut.png` | not found in the repository |
| `documentation/v2/30-39/32-dashboards.md` | 1090 | `../../../environment_setup/aifactory/azure_dashboards` | not found in the repository |
| `documentation/v2/30-39/33-install-azureml-sdk-v1+v2.md` | 72 | `../esml/images/quickstart_notebooks_2_select_conda.png` | not found in the repository |
| `documentation/v2/30-39/35-setup-aifactory-notebook-templates-py.md` | 26 | `../../../../settings/enterprise_specific/*` | points outside the repository |
| `documentation/v2/30-39/35-setup-aifactory-notebook-templates-py.md` | 27 | `../../../../settings/project_specific/*` | points outside the repository |
| `documentation/v2/30-39/37-datascientist-ml-acceleration.md` | 118 | `../../../l/esml/images/01_setup_model_1.png` | not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry_usage_report.py` | 24 | `azure.core.exceptions` | module not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry_usage_report.py` | 25 | `azure.identity` | module not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry_usage_report.py` | 26 | `azure.mgmt.monitor` | module not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry_usage_report.py` | 27 | `azure.mgmt.resource` | module not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry_usage_report.py` | 28 | `azure.monitor.query` | module not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/automation/projectteam/foundry-usage/foundry_usage_report.py` | 817 | `output/foundry-usage-*.pdf` | the pattern matches no file |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-1-genai-networking.yaml` | 858 | `aifactory/parameters/subnetParameters.json` | not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md` | 112 | `../../../../aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml` | not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md` | 188 | `../../../../aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml` | not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh` | 770 | `/dev/null` | not found in the repository |
| `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh` | 772 | `/dev/null` | not found in the repository |
| `environment_setup/aifactory/bicep/personas/inspect_manifest.py` | 10 | `personas` | module not found in the repository |
| `environment_setup/aifactory/bicep/personas/inspect_manifest.py` | 12 | `.` | module not found in the repository |
| `environment_setup/aifactory/bicep/personas/pipeline.py` | 15 | `personas` | module not found in the repository |
| `environment_setup/aifactory/bicep/personas/pipeline.py` | 18 | `.` | module not found in the repository |
| `environment_setup/aifactory/bicep/scripts/databricks/init_scripts/capture_log_metrics.sh` | 152 | `onboard_agent.sh` | not found in the repository |
| `environment_setup/aifactory/bicep/scripts/delete-services-if-disabled.sh` | 100 | `*/project-deletion.py` | the pattern matches no file |
| `environment_setup/azurefactory-cli/setup.py` | 21 | `../../azure-enterprise-scale-ml/bootstrap/lib/*` | the pattern matches no file |
| `environment_setup/azurefactory-cli/setup.py` | 22 | `../../lib/*` | the pattern matches no file |
| `environment_setup/azurefactory-cli/tests/test_documentation_site.py` | 270 | `../../../documentation/gh-io/docs/templates` | not found in the repository |
| `environment_setup/azurefactory-cli/tests/test_documentation_site.py` | 456 | `../../../documentation/gh-io/tools/architecture_icons/foundry.svg` | not found in the repository |

518 more rows are not shown; plan.json has all of them.

## Tests and docs (followers)

A follower stays when what it belongs to stays. It never keeps code alive.

| Group | Kept | Dropped |
|---|---:|---:|
| docs | 200 | 0 |
| repository | 8 | 0 |
| tests | 286 | 0 |

## Submodule links and symlinks

None.

## Verification

The verify commands have not been run on this plan.

## Warnings

- esml/images/01_setup_model_10.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/01_setup_model_3.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/01_setup_model_9.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/23_esml_pipeline_overview_intro.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/aml-pipeline_batch_ppt-3.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/deploy-to-aks.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-automapping.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-mlops-2.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-s01e01-3.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-s02e01-challenge.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-s02e01-the-solution.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-settings.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/esml-testset-scoring.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/mlops-env-arg.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/split_gold_and_train_automl_small.png matches drop (esml/**) and a more specific keep or root; it is kept
- esml/images/templates-aml.png matches drop (esml/**) and a more specific keep or root; it is kept
- drop: '**/previous-release/**' matches no file
- drop: 'environment_setup/install_tutorial_guide/old/**' matches no file
- drop: 'environment_setup/install_config_wizard/maui/*.cab' matches no file
- drop: 'environment_setup/install_config_wizard/maui/*.msi' matches no file
- drop: 'environment_setup/install_tutorial_guide/*.cab' matches no file
- drop: 'environment_setup/install_tutorial_guide/*.msi' matches no file
- drop: 'environment_setup/aifactory/azure_dashboards/ESML-AIFactory-1.json' matches no file
- drop: 'environment_setup/aifactory/azure_dashboards/ESML-AIFactory-DEV.json' matches no file
- drop: 'environment_setup/aifactory/azure_dashboards/ESML-AIFactory-Dev-v2.json' matches no file
- drop: 'environment_setup/aifactory/azure_dashboards/ESML-AIFactory-v2.json' matches no file
- drop: 'environment_setup/aifactory/bicep/cleanup-role-assignments.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-common/modules-common/nsgCommonScoring.json' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-genai-1/21-sample-app.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-project/21-network.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-assign-roles-on-rg.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-assign-roles-on-sub.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-assigned-roles-del-on-rg.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-cost-from-rg-tag.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-create-compute-instance-in-vnet.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-delete-subnets-for-project.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-deleteCapHost.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-get_your_own_object_id.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-list-rbac-for-user-on-rg.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-load-env-file.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-update-az-add-ml-extension.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/000-update-storage-account-access.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/001-set-owner-on-sub.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/001-set-privateDnsZoneContrib-on-RG.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/002-set-accesspolicy-for-sp.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/003-set-BlobDataOwner-to-sp.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/10-generate-pwd-4-ado.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/100-aml-rbac.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/12-GENAI-update-ip-rule-cmd.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/23-add-dsvm.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/23-install-sdks-on-win11.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/26-remove-esml-coreteam-member.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/26-remove-esml-project-member.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/30-vpn-gateway-certificates.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/31-create-priv-dns-zones-if-not-exists.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/_24-add-aks.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/esml-util/_25-add-users-to-bastion.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/applicationInsights.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/common/CmnRoleAssignments.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csDocIntelligence-kvSecret.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/aiFoundry2025.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/azuredeploy.parameters.json' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/deleteAllCapHosts.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/deleteCapHost.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/listCapHosts.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/listCapHosts.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim/modules-network-secured/ai-project-identity.json' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csSpeech-kvSecret.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/csVision-kvSecret.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/dataLakeVnetRules.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/databases/cosmosdb/cosmosCustomRole.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/databases/elasticsearch/elasticsearch-rbac-example.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/databricksAssets.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/diagnosticSettingCognitive.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/diagnostics/eventHubDiagnostics.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/diagnostics/logAnalyticsWorkspaceDiagnostics.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/monitoring/Get-AmplsResources.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/monitoring/amplsApplicationInsightsManager.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/monitoring/amplsHub.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/monitoring/getAmplsApplicationInsights.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/policyExcemptions/policy-exempt-foundry-subnets.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/privateDnsZone.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/readerRbac.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/resourcegroupManaged.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/modules/verify-acr-rbac.bicep' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/databricks/deployment/_pre_cluster_create.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/databricks/deployment/create_cluster.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/databricks/deployment/create_secret_scope.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/databricks/deployment/post_cluster_create.sh' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/enableADDloginPostDeploy.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/test-git-functionality.ps1' matches no file
- drop: 'environment_setup/aifactory/bicep/scripts/test-submodule-detection.ps1' matches no file
- drop: 'esml/azure_provisioning/azure_devops_pipelines/Build_pipelines/Dev/ESML-project002_M03-Dev.json' matches no file
- drop: 'esml/azure_provisioning/azure_devops_pipelines/Build_pipelines/Test_Prod/ESML-project002_M03-Test_Prod.json' matches no file
- drop: 'esml/azure_provisioning/azure_devops_pipelines/Release/Dev/Release-Online-Dev.json' matches no file
- drop: 'esml/azure_provisioning/azure_devops_pipelines/Release/Test_Prod/Release-Online-Test_Prod.json' matches no file

## Broken references in the compacted tree

A kept file names a file that is dropped.

| File | Line | Target | Why |
|---|---:|---|---|
| `documentation/architecture/architecture/Repository-Boundaries.md` | 8 | `esmlfac/adapter.py` | the profile drops the target |
| `documentation/architecture/ml-lifecycle/Engines-and-Pipelines.md` | 12 | `esmlfac/adapter.py` | the profile drops the target |
| `documentation/v2/20-29/24-legacy-v124-setup.md` | 429 | `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_settings.json` | the profile drops the target |
| `documentation/v2/20-29/24-legacy-v124-setup.md` | 431 | `copy_my_subfolders_to_my_grandparent/settings/project_specific/security_config.json` | the profile drops the target |
| `documentation/v2/20-29/24-legacy-v124-setup.md` | 433 | `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/lake_settings.json` | the profile drops the target |
| `documentation/v2/30-39/32-use_cases-where_to_start.md` | 24 | `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/lake_settings.json` | the profile drops the target |
| `documentation/v2/30-39/33-install-azureml-sdk-v1+v2.md` | 6 | `environment_setup/install_sdk/user_dev_env_install/AzureML_v1_55_and_v2_1_15.zip` | the profile drops the target |
| `documentation/v2/30-39/33-install-azureml-sdk-v1+v2.md` | 68 | `copy_my_subfolders_to_my_grandparent/02_update_templates_QUICK.ipynb` | the profile drops the target |
| `documentation/v2/30-39/33-install-azureml-sdk-v1+v2.md` | 69 | `copy_my_subfolders_to_my_grandparent/01_init_templates_ALL.ipynb` | the profile drops the target |
| `documentation/v2/30-39/35-setup-aifactory-notebook-templates-py.md` | 18 | `copy_my_subfolders_to_my_grandparent/settings/project_specific/model/lake_settings.json` | the profile drops the target |
| `documentation/v2/30-39/35-setup-aifactory-notebook-templates-py.md` | 22 | `copy_my_subfolders_to_my_grandparent/settings/enterprise_specific/dev_test_prod_settings.json` | the profile drops the target |
| `documentation/v2/30-39/35-setup-aifactory-notebook-templates-py.md` | 23 | `copy_my_subfolders_to_my_grandparent/settings/project_specific/security_config.json` | the profile drops the target |
| `documentation/v2/30-39/35-setup-aifactory-notebook-templates-py.md` | 25 | `copy_my_subfolders_to_my_grandparent/settings/active_dev_test_prod.json` | the profile drops the target |
| `usecase_code/50-ml-model-factory/accelerator/tests/test_lifecycle_e2e.py` | 538 | `copy_my_subfolders_to_my_grandparent/notebook_templates/model_diabetes/model.pkl` | the profile drops the target |

## Restore a file

Every dropped file is still in the base commit:

```
git checkout 550e8f4a9e848ffcfa782b59fe9bb1410032d633 -- <path>
```
