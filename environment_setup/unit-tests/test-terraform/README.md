# Terraform port test suite

Offline tests of `environment_setup/aifactory/terraform` against the Bicep it ports
(`bicep/esml-common/main/11-rgCommon.bicep`, `12-networkCommon.bicep`, `13-rgLevel.bicep`). Nothing logs in to
Azure, plans against Azure or deploys. CI runs it in the job "Terraform" of
`.github/workflows/infrastructure-tests.yml`, on Ubuntu and Windows.

| Tier | Files | What |
|---|---|---|
| 1 static | `test_format_and_generated.py`, `test_parity_map.py`, `test_terraform_workflow.py`, `test_tiers.py` | `terraform fmt`; generated files are current; every Bicep resource type is mapped and implemented; the GitHub Actions template mirrors `infra-common.yml`; CI wiring |
| 2 parity | `test_validate.py`, `test_unique_string.py`, `test_stage_parity.py` | `init -backend=false` + `validate`; `uniqueString` equals the Bicep compiler's; parameters, names and conditions of 11/12/13 equal the Bicep, scenario by scenario |

Both Terraform and Bicep are required: a missing tool fails the suite instead of skipping tests. The tier
mechanism is the one of `test-bicep` (`base/tiers.py`); every tier runs by default.

```bash
python -m pip install -r environment_setup/unit-tests/test-bicep/requirements.txt
```

```bash
python environment_setup/unit-tests/test-terraform/run_ci.py --terraform "$(command -v terraform)" --bicep "$(command -v bicep)"
```

The Bicep compiler must have restored the public registry modules of 13-rgLevel once
(`bicep restore environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep`). Terraform downloads
azurerm and azapi from the registry; offline, point `TF_CLI_CONFIG_FILE` at a CLI configuration with a
filesystem mirror.

How the parity tests work:

* **Bicep side.** `bicep build` compiles each entry file (with symbolic names, in a temporary copy). The
  workflow replay (`harness.replay_bicep_workflow`) gives the `--parameters` of steps 01/02/03 for a
  variables.json. `test-bicep/base/arm_expressions.py` then evaluates the name variables and every module
  condition. `uniqueString` uses the suite's Python oracle, which `test_unique_string.py` first checks against
  `bicep build-params`.
* **Terraform side.** `terraform console` evaluates the root module, or a wrapper that calls the stage modules
  directly, with no plan and no provider configuration: `local.p11/p12/p13`, the stages' `deploy` maps (the
  only inputs of their counts) and their name maps.
