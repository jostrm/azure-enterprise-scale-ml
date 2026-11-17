"""Adopt-then-apply: infra-common-terraform.yml takes over resources THIS factory already has (Bicep parity).

The Registered Full bootstrap creates the common resource group, the VNet with its subnets and NSGs, the own hub and
the seeding Key Vault before the common workflow runs. infra-common.yml PUTs them again (create-or-update); the
Terraform port failed instead (aif-164, runs 44086929279 and 44087682374, 2026-11-17):

    Error: a resource with the ID ".../resourceGroups/aif64-esml-common-sdc-dev-001" already exists - to be managed
    via Terraform this resource needs to be imported into the State.

terraform/tools/tf_adopt.py turns each such diagnostic into a Terraform import block (refusing ids outside this
factory's subscription and resource groups) and refuses a plan that would delete or replace an adopted resource;
terraform/tools/aif-tf-adopt.sh runs plan-and-apply again after each adoption round, at most N rounds. Offline:
no Terraform, no Azure. The Bash tests require bash (Git Bash on Windows), like the workflow step itself.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from harness import TERRAFORM_DIR

TOOLS = TERRAFORM_DIR / "tools"
HELPER = TOOLS / "tf_adopt.py"
LOOP = TOOLS / "aif-tf-adopt.sh"

SUBSCRIPTION = "f0fe8b33-73bf-41e4-9997-e3920d793c06"
COMMON_RG = "aif64-esml-common-sdc-dev-001"
RG_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{COMMON_RG}"
RG_ADDRESS = "module.stage_11.module.rgCommon.azurerm_resource_group.common_resource_un_managed"
KV_ID = RG_ID + "/providers/Microsoft.KeyVault/vaults/kv-cmndev-ayxph-001"
KV_ADDRESS = "module.stage_13.module.kvCmn[0].azapi_resource.key_vault"
ROLE_ADDRESS = ('module.stage_11.module.contributorPermissions.azurerm_role_assignment.contributor_role2user_or_group'
                '["c02e343c-4c2b-4b24-b99a-d0c1d0226519"]')
ROLE_ID = RG_ID + "/providers/Microsoft.Authorization/roleAssignments/0b0c55a5-6a8c-5d9b-9c0d-6f3e2a1b4c5d"

# The diagnostic of run 44087682374 as the step log shows it (-no-color).
LIVE_ERROR = f'''
Error: a resource with the ID "{RG_ID}" already exists - to be managed via Terraform this resource needs to be imported into the State. Please see the resource documentation for "azurerm_resource_group" for more information

  with {RG_ADDRESS},
  on ../modules/resource-group-unmanaged/main.tf line 6, in resource "azurerm_resource_group" "common_resource_un_managed":
   6: resource "azurerm_resource_group" "common_resource_un_managed" {{

'''

# azapi spells it with a capital A; a terminal can wrap the text and draw the diagnostic box.
AZAPI_BOXED_WRAPPED = f'''
│ Error: A resource with the ID "{KV_ID}" already exists - to be
│ managed via Terraform this resource needs to be imported into the State. Please see the resource documentation
│ for "azapi_resource" for more information.
│
│   with {KV_ADDRESS},
│   on ../modules/key-vault/main.tf line 12, in resource "azapi_resource" "key_vault":
│   12: resource "azapi_resource" "key_vault" {{
│
'''

ROLE_ERROR = f'''
Error: a resource with the ID "{ROLE_ID}" already exists - to be managed via Terraform this resource needs to be imported into the State. Please see the resource documentation for "azurerm_role_assignment" for more information

  with {ROLE_ADDRESS},
  on ../modules/rbac/main.tf line 3, in resource "azurerm_role_assignment" "contributor_role2user_or_group":
'''

OTHER_ERROR = '''
Error: creating Key Vault: unexpected status 403 (403 Forbidden) with error: AuthorizationFailed: The client does not have authorization

  with module.stage_13.module.kvAdmin[0].azapi_resource.key_vault,
  on ../modules/key-vault/main.tf line 12, in resource "azapi_resource" "key_vault":
'''


def load_helper():
    assert HELPER.is_file(), f"{HELPER} is missing"
    spec = importlib.util.spec_from_file_location("tf_adopt", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def error_text(resource_id: str, address: str, kind: str = "azurerm_resource_group") -> str:
    return (f'\nError: a resource with the ID "{resource_id}" already exists - to be managed via Terraform this '
            f'resource needs to be imported into the State. Please see the resource documentation for "{kind}" for '
            f'more information\n\n  with {address},\n  on main.tf line 1, in resource "{kind}" "x":\n')


# ------------------------------------------------------------------------------------------ diagnostics


def test_the_live_aif164_diagnostic_yields_the_address_and_the_arm_id():
    assert load_helper().existing_resources(LIVE_ERROR) == [(RG_ADDRESS, RG_ID)]


def test_azapi_wording_wrapped_lines_box_drawing_and_for_each_keys_are_read():
    found = load_helper().existing_resources(AZAPI_BOXED_WRAPPED + ROLE_ERROR + LIVE_ERROR + LIVE_ERROR)
    assert found == [(KV_ADDRESS, KV_ID), (ROLE_ADDRESS, ROLE_ID), (RG_ADDRESS, RG_ID)], "in order, without repeats"


def test_other_errors_are_not_adoptions():
    assert load_helper().existing_resources(OTHER_ERROR) == []
    no_address = LIVE_ERROR.replace(f"  with {RG_ADDRESS},\n", "")
    assert load_helper().existing_resources(no_address) == []


# ---------------------------------------------------------------------------------------------- scope


@pytest.mark.parametrize("resource_id", [
    RG_ID, RG_ID.upper().replace("SUBSCRIPTIONS", "subscriptions"), KV_ID, ROLE_ID,
    KV_ID + "|kv-diagnostics",  # azurerm composite id of a diagnostic setting
])
def test_ids_of_this_factory_are_in_scope(resource_id):
    assert load_helper().in_scope(resource_id, SUBSCRIPTION, [COMMON_RG])


@pytest.mark.parametrize("resource_id", [
    RG_ID.replace(SUBSCRIPTION, "00000000-0000-0000-0000-000000000000"),
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/aif64-esml-project001-sdc-dev-001-rg",
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{COMMON_RG}-other",
    f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Security/pricings/AI",
    f"/subscriptions/{SUBSCRIPTION}",
    "/providers/Microsoft.Management/managementGroups/root",
    "kv-cmndev-ayxph-001",
])
def test_ids_outside_this_factory_are_refused(resource_id):
    assert not load_helper().in_scope(resource_id, SUBSCRIPTION, [COMMON_RG])


def test_a_second_resource_group_widens_the_scope_only_to_that_group():
    vnet_rg = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/byo-vnet-rg"
    helper = load_helper()
    assert helper.in_scope(vnet_rg, SUBSCRIPTION, [COMMON_RG, "BYO-VNET-RG", ""])
    assert not helper.in_scope(vnet_rg, SUBSCRIPTION, [COMMON_RG, ""])


# --------------------------------------------------------------------------------------- adopt command


def adopt(tmp_path: Path, errors: str, *groups: str, plan_json: Path | None = None) -> subprocess.CompletedProcess:
    (tmp_path / "errors.log").write_text(errors, encoding="utf-8")
    arguments = [sys.executable, str(HELPER), "adopt", "--errors", str(tmp_path / "errors.log"),
                 "--imports", str(tmp_path / "aif_adopted_imports.tf"), "--subscription", SUBSCRIPTION]
    for group in groups or (COMMON_RG,):
        arguments += ["--resource-group", group]
    if plan_json:
        arguments += ["--plan-json", "-"]
    return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", check=False, timeout=60,
                          input=plan_json.read_text(encoding="utf-8") if plan_json else None)


def test_adopt_writes_one_import_block_per_existing_resource_and_exits_0(tmp_path):
    result = adopt(tmp_path, LIVE_ERROR + AZAPI_BOXED_WRAPPED)
    assert result.returncode == 0, result.stderr
    imports = (tmp_path / "aif_adopted_imports.tf").read_text(encoding="utf-8")
    assert f'import {{\n  to = {RG_ADDRESS}\n  id = "{RG_ID}"\n}}\n' in imports
    assert f'import {{\n  to = {KV_ADDRESS}\n  id = "{KV_ID}"\n}}\n' in imports
    assert RG_ID in result.stderr and RG_ADDRESS in result.stderr, "each adoption is named in the log"
    assert load_helper().adopted(tmp_path / "aif_adopted_imports.tf") == {RG_ADDRESS: RG_ID, KV_ADDRESS: KV_ID}


def test_adopt_appends_new_resources_and_exits_3_when_nothing_new_is_left(tmp_path):
    assert adopt(tmp_path, LIVE_ERROR).returncode == 0
    assert adopt(tmp_path, ROLE_ERROR).returncode == 0
    assert set(load_helper().adopted(tmp_path / "aif_adopted_imports.tf")) == {RG_ADDRESS, ROLE_ADDRESS}
    again = adopt(tmp_path, LIVE_ERROR)
    assert again.returncode == 3, "an address that is already adopted and still fails is not adopted twice"
    assert adopt(tmp_path, OTHER_ERROR).returncode == 3


def test_adopt_refuses_every_import_when_one_id_is_outside_this_factory(tmp_path):
    foreign = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/someone-elses-rg"
    result = adopt(tmp_path, LIVE_ERROR + error_text(foreign, "module.stage_11.module.other.azurerm_resource_group.x"))
    assert result.returncode == 2
    assert foreign in result.stderr and "::error::" in result.stderr
    assert not (tmp_path / "aif_adopted_imports.tf").exists(), "nothing is adopted when one id is refused"


def test_adopt_refuses_an_address_that_is_not_a_resource_address(tmp_path):
    result = adopt(tmp_path, error_text(RG_ID, 'module.a.azurerm_resource_group.x }\nimport { to = y'))
    assert result.returncode in (2, 3)
    assert not (tmp_path / "aif_adopted_imports.tf").exists()


def test_azapi_imports_read_with_the_api_version_the_configuration_uses(tmp_path):
    """azapi imports an id without ?api-version= with the newest API version; the failed round's saved plan names
    the configured one (change.after.type "<type>@<version>"), so the adopted resource is read as configured."""
    saved = json.dumps({"resource_changes": [
        {"address": KV_ADDRESS, "type": "azapi_resource",
         "change": {"actions": ["create"], "after": {"type": "Microsoft.KeyVault/vaults@2024-11-01"}}},
        {"address": RG_ADDRESS, "type": "azurerm_resource_group", "change": {"actions": ["create"], "after": {}}}]})
    (tmp_path / "plan.json").write_text(saved, encoding="utf-8")
    result = adopt(tmp_path, LIVE_ERROR + AZAPI_BOXED_WRAPPED, plan_json=tmp_path / "plan.json")
    assert result.returncode == 0, result.stderr
    assert load_helper().adopted(tmp_path / "aif_adopted_imports.tf") == {
        RG_ADDRESS: RG_ID, KV_ADDRESS: KV_ID + "?api-version=2024-11-01"}
    assert load_helper().in_scope(KV_ID + "?api-version=2024-11-01", SUBSCRIPTION, [COMMON_RG])


def test_an_unreadable_saved_plan_still_adopts_with_the_plain_id(tmp_path):
    (tmp_path / "plan.json").write_text("", encoding="utf-8")
    result = adopt(tmp_path, AZAPI_BOXED_WRAPPED, plan_json=tmp_path / "plan.json")
    assert result.returncode == 0, result.stderr
    assert load_helper().adopted(tmp_path / "aif_adopted_imports.tf") == {KV_ADDRESS: KV_ID}


def test_import_ids_are_written_as_literal_hcl_strings():
    text = load_helper().import_block("module.a.azurerm_resource_group.x", '/subscriptions/x/resourceGroups/a"${b}\\')
    assert 'id = "/subscriptions/x/resourceGroups/a\\"$${b}\\\\"' in text


# ----------------------------------------------------------------------------------------- plan guard


def plan(*changes: tuple[str, list[str], bool]) -> str:
    return json.dumps({"format_version": "1.2", "resource_changes": [
        {"address": address, "change": {"actions": actions, **({"importing": {"id": "x"}} if importing else {})}}
        for address, actions, importing in changes]})


def check_plan(tmp_path: Path, plan_json: str, adopted: dict[str, str]) -> subprocess.CompletedProcess:
    imports = tmp_path / "aif_adopted_imports.tf"
    if adopted:
        imports.write_text("".join(load_helper().import_block(a, i) for a, i in adopted.items()), encoding="utf-8")
    return subprocess.run([sys.executable, str(HELPER), "check-plan", "--imports", str(imports)], input=plan_json,
                          capture_output=True, text=True, encoding="utf-8", check=False, timeout=60)


@pytest.mark.parametrize("actions", [["delete", "create"], ["create", "delete"], ["delete"]])
def test_a_plan_that_deletes_or_replaces_an_adopted_resource_is_refused(tmp_path, actions):
    result = check_plan(tmp_path, plan((RG_ADDRESS, actions, False), (KV_ADDRESS, ["update"], False)),
                        {RG_ADDRESS: RG_ID})
    assert result.returncode == 2
    assert RG_ADDRESS in result.stderr and "::error::" in result.stderr


def test_a_plan_that_replaces_a_resource_while_importing_it_is_refused(tmp_path):
    result = check_plan(tmp_path, plan((KV_ADDRESS, ["create", "delete"], True)), {})
    assert result.returncode == 2 and KV_ADDRESS in result.stderr


def test_in_place_updates_of_adopted_resources_and_unrelated_changes_pass(tmp_path):
    result = check_plan(tmp_path, plan((RG_ADDRESS, ["update"], True), (KV_ADDRESS, ["no-op"], True),
                                       ("module.stage_13.module.vmPrivate[0].azapi_resource.virtual_machine[0]",
                                        ["delete"], False), ("module.x.azurerm_key_vault.y", ["create"], False)),
                        {RG_ADDRESS: RG_ID, KV_ADDRESS: KV_ID})
    assert result.returncode == 0, result.stderr


def test_a_plan_without_adoptions_passes(tmp_path):
    assert check_plan(tmp_path, plan(("module.x.azurerm_key_vault.y", ["delete"], False)), {}).returncode == 0


# ------------------------------------------------------------------------------- the Bash adoption loop


def bash_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


# fake_plan_apply plays one outcome per call from $OUTCOMES (ok, or a file name under $WORK/errors whose text it
# writes to stderr); every call is logged. A `terraform` function stands in for `terraform show -json`.
HARNESS = r"""
calls="$WORK/calls"; : > "$calls"
fake_plan_apply() {
  echo "call" >> "$calls"
  n=$(grep -c '^call' "$calls")
  outcome=$(echo "$OUTCOMES" | cut -d' ' -f"$n")
  if [ "${outcome:-ok}" = ok ]; then echo "applied on call $n"; return 0; fi
  echo "plan output of call $n"
  cat "$WORK/errors/$outcome" >&2
  return "${FAIL_CODE:-1}"
}
terraform() { cat "$WORK/plan.json"; }
source "$LOOP"
"""


def run_loop(tmp_path: Path, outcomes: str, errors: dict[str, str], *, rounds: int | None = None,
             command: str | None = None, plan_json: str | None = None, environment: dict | None = None):
    bash = bash_executable()
    assert bash, "bash is required (Git Bash on Windows): the workflow step runs this loop in bash"
    assert LOOP.is_file(), f"{LOOP} is missing"
    (tmp_path / "errors").mkdir(exist_ok=True)
    for name, text in errors.items():
        (tmp_path / "errors" / name).write_text(text, encoding="utf-8")
    (tmp_path / "root").mkdir(exist_ok=True)
    if plan_json is not None:
        (tmp_path / "plan.json").write_text(plan_json, encoding="utf-8")
    command = command or (f'aif_tf_adopt --root "$WORK/root" --subscription {SUBSCRIPTION} '
                          f'--resource-group {COMMON_RG} --resource-group "" -- fake_plan_apply')
    env = {key: value for key, value in os.environ.items() if not key.startswith(("AIF_", "GITHUB_"))}
    env |= {"WORK": tmp_path.as_posix(), "LOOP": LOOP.as_posix(), "OUTCOMES": outcomes,
            "AIF_PYTHON": Path(sys.executable).as_posix(), "PYTHONUTF8": "1"}
    if rounds:
        env["AIF_TF_ADOPT_ROUNDS"] = str(rounds)
    env |= environment or {}
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-s"],
                            input=(HARNESS + command + "\n").encode("utf-8"), capture_output=True, check=False,
                            timeout=120, env=env)
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    imports = tmp_path / "root" / "aif_adopted_imports.tf"
    return (result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8"), len(calls),
            imports.read_text(encoding="utf-8") if imports.exists() else "")


def test_the_loop_adopts_the_existing_resource_group_and_applies_again(tmp_path):
    code, out, err, calls, imports = run_loop(tmp_path, "rg ok", {"rg": LIVE_ERROR})
    assert (code, calls) == (0, 2), err
    assert f"to = {RG_ADDRESS}" in imports and RG_ID in imports
    assert "applied on call 2" in out
    assert "already exists" not in err, "an adopted round's errors are logged on stdout, not given to aif_retry"
    assert "already exists" in out


def test_the_loop_reads_the_saved_plan_of_the_failed_round_for_azapi_api_versions(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "tfplan").write_text("binary plan", encoding="utf-8")
    saved = json.dumps({"resource_changes": [{"address": KV_ADDRESS, "type": "azapi_resource", "change": {
        "actions": ["create"], "after": {"type": "Microsoft.KeyVault/vaults@2024-11-01"}}}]})
    code, _, err, calls, imports = run_loop(tmp_path, "kv ok", {"kv": AZAPI_BOXED_WRAPPED}, plan_json=saved)
    assert (code, calls) == (0, 2), err
    assert f'id = "{KV_ID}?api-version=2024-11-01"' in imports


def test_the_loop_adopts_round_after_round_until_the_apply_succeeds(tmp_path):
    errors = {"rg": LIVE_ERROR, "kv": AZAPI_BOXED_WRAPPED, "role": ROLE_ERROR}
    code, _, err, calls, imports = run_loop(tmp_path, "rg kv role ok", errors)
    assert (code, calls) == (0, 4), err
    assert all(address in imports for address in (RG_ADDRESS, KV_ADDRESS, ROLE_ADDRESS))


def test_the_loop_is_bounded(tmp_path):
    errors = {f"r{n}": error_text(f"{RG_ID}/providers/Microsoft.Network/networkSecurityGroups/nsg{n}",
                                  f"module.stage_13.module.nsg{n}.azurerm_network_security_group.this")
              for n in range(1, 6)}
    code, _, err, calls, _ = run_loop(tmp_path, "r1 r2 r3 r4 r5 ok", errors, rounds=3,
                                      environment={"FAIL_CODE": "5"})
    assert (code, calls) == (5, 3), err
    assert "3 rounds" in err and "nsg3" in err, "the last round's error is shown and the bound is named"


def test_any_other_failure_returns_at_once_with_its_code_and_stderr_for_aif_retry(tmp_path):
    code, _, err, calls, imports = run_loop(tmp_path, "other ok", {"other": OTHER_ERROR},
                                            environment={"FAIL_CODE": "7"})
    assert (code, calls, imports) == (7, 1, "")
    assert "AuthorizationFailed" in err


def test_an_id_outside_this_factory_stops_the_loop_without_adopting(tmp_path):
    foreign = error_text(f"/subscriptions/{SUBSCRIPTION}/resourceGroups/someone-elses-rg",
                         "module.stage_11.module.other.azurerm_resource_group.x")
    code, _, err, calls, imports = run_loop(tmp_path, "foreign ok", {"foreign": foreign})
    assert (code, calls, imports) == (1, 1, "")
    assert "someone-elses-rg" in err and "::error::" in err


def test_the_plan_guard_refuses_to_replace_an_adopted_resource(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "aif_adopted_imports.tf").write_text(load_helper().import_block(RG_ADDRESS, RG_ID),
                                                              encoding="utf-8")
    code, _, err, _, _ = run_loop(tmp_path, "", {}, plan_json=plan((RG_ADDRESS, ["delete", "create"], False)),
                                  command='aif_tf_check_plan "$WORK/root" tfplan || echo "status $?" >&2')
    assert "status 2" in err and RG_ADDRESS in err


def test_the_plan_guard_passes_an_in_place_update(tmp_path):
    code, _, err, _, _ = run_loop(tmp_path, "", {}, plan_json=plan((RG_ADDRESS, ["update"], True)),
                                  command='aif_tf_check_plan "$WORK/root" tfplan && echo "status 0" >&2')
    assert "status 0" in err, err


def test_the_common_resource_group_name_is_the_state_key_and_bicep_name(tmp_path):
    command = ('admin_aifactoryPrefixRG=aif64- admin_locationSuffix=sdc admin_aifactorySuffixRG=-001 '
               'aif_tf_common_resource_group dev; commonResourceGroup_param=given-rg aif_tf_common_resource_group dev')
    code, out, err, _, _ = run_loop(tmp_path, "", {}, command=command)
    assert code == 0, err
    assert out.splitlines() == [COMMON_RG, "given-rg"]
