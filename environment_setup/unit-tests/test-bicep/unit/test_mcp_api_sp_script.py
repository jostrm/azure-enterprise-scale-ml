"""Offline contract for esml-util/29b-create-mcp-api-sp-for-projects.sh, run against a fake Azure CLI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from base.config import REPO_ROOT

SCRIPT = REPO_ROOT / "environment_setup/aifactory/bicep/esml-util/29b-create-mcp-api-sp-for-projects.sh"
BASH = shutil.which("bash")

# Records every call; GETs answer from files under $FAKE_STATE so a second run sees the first run's apps.
FAKE_AZ = r"""#!/bin/bash
state="$FAKE_STATE"
echo "$*" >> "$state/calls.log"
case "$1 $2" in
  "ad app")
    case "$3" in
      list) name="$5"; [ -f "$state/app-$name" ] && cat "$state/app-$name"; exit 0 ;;
      create) name="$5"; n=$(ls "$state" | grep -c '^app-'); id="0000000$((n + 1))-0000-4000-8000-000000000000"
              echo "$id" > "$state/app-$name"; echo "$id"; exit 0 ;;
      show) case "$*" in *"--query id"*) echo "obj-$5" ;; *) cat "$state/roles-$5" 2>/dev/null || echo "[]" ;; esac; exit 0 ;;
    esac ;;
  "ad sp")
    case "$3" in
      list) id=$(echo "$*" | sed -E "s/.*appId eq '([^']+)'.*/\1/"); [ -f "$state/sp-$id" ] && cat "$state/sp-$id"; exit 0 ;;
      create) echo "sp-$5" > "$state/sp-$5"; echo "sp-$5"; exit 0 ;;
    esac ;;
  "rest --method")
    body=$(echo "$*" | sed -E 's/.*--body @([^ ]+).*/\1/'); uri=$(echo "$*" | sed -E 's/.*applications\/([^ ]+).*/\1/')
    cp "$body" "$state/patch-${uri#obj-}.json"; exit 0 ;;
  "keyvault secret") echo "$*" >> "$state/secrets.log"; exit 0 ;;
  "account set"|"login --tenant") exit 0 ;;
esac
echo "unexpected az $*" >&2
exit 1
"""


def run(tmp_path, **env):
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir(exist_ok=True)
    state.mkdir(exist_ok=True)
    fake = bin_dir / "az"
    fake.write_text(FAKE_AZ, encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    values = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_STATE": str(state), "TMPDIR": str(tmp_path),
              "KEY_VAULT_NAME": "kv-seeding", "SUBSCRIPTION_ID": "sub", "TENANT_ID": "tenant", "SKIP_LOGIN": "true",
              **env}
    result = subprocess.run([BASH, str(SCRIPT), "--yes"], capture_output=True, text=True, env=values, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return state


pytestmark = pytest.mark.skipif(not BASH, reason="bash is required")


def test_a_range_creates_one_secretless_mcp_api_sp_per_project_and_stores_its_ids(tmp_path):
    state = run(tmp_path, PROJECT_NUMBER_FROM="001", PROJECT_NUMBER_TO="002")
    calls = (state / "calls.log").read_text(encoding="utf-8")
    assert calls.count("ad app create --display-name esml-project001-mcp-api") == 1
    assert calls.count("ad app create --display-name esml-project002-mcp-api") == 1
    assert "credential" not in calls and "create-for-rbac" not in calls, "the MCP SP never gets a secret"
    patch = json.loads((state / "patch-00000001-0000-4000-8000-000000000000.json").read_text(encoding="utf-8"))
    assert patch["identifierUris"] == ["api://00000001-0000-4000-8000-000000000000"]
    assert patch["api"] == {"requestedAccessTokenVersion": 2}, "the MCP accepts only v2 tokens"
    assert [(role["value"], role["allowedMemberTypes"], role["isEnabled"]) for role in patch["appRoles"]] == [
        ("AiFactory.Mcp.Read", ["Application"], True)]
    secrets = (state / "secrets.log").read_text(encoding="utf-8")
    for line in ("--name esml-project001-mcp-app-id --value 00000001-0000-4000-8000-000000000000",
                 "--name esml-project001-mcp-sp-oid --value sp-00000001-0000-4000-8000-000000000000",
                 "--name esml-project002-mcp-app-id --value 00000002-0000-4000-8000-000000000000"):
        assert line in secrets


def test_a_rerun_completes_existing_apps_without_duplicating_them_or_their_role(tmp_path):
    state = run(tmp_path)
    app_id = "00000001-0000-4000-8000-000000000000"
    existing = json.loads((state / f"patch-{app_id}.json").read_text(encoding="utf-8"))["appRoles"]
    (state / f"roles-{app_id}").write_text(json.dumps(existing), encoding="utf-8")
    (state / "calls.log").unlink()
    run(tmp_path)
    calls = (state / "calls.log").read_text(encoding="utf-8")
    assert "ad app create" not in calls and "ad sp create" not in calls
    assert json.loads((state / f"patch-{app_id}.json").read_text(encoding="utf-8"))["appRoles"] == existing


def test_an_invalid_range_stops_before_any_azure_call(tmp_path):
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    run(tmp_path, PROJECT_NUMBER_FROM="001")
    (state / "calls.log").unlink()
    values = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_STATE": str(state), "TMPDIR": str(tmp_path),
              "SKIP_LOGIN": "true", "PROJECT_NUMBER_FROM": "005", "PROJECT_NUMBER_TO": "002"}
    result = subprocess.run([BASH, str(SCRIPT), "--yes"], capture_output=True, text=True, env=values, timeout=60)
    assert result.returncode != 0
    assert not (state / "calls.log").exists()


PROJECT_SCRIPT = REPO_ROOT / "environment_setup/aifactory/bicep/esml-util/29-create-sp-or-update-oid-for-project.sh"
FAKE_AZ_PROJECT = r"""#!/bin/bash
echo "$*" >> "$FAKE_STATE/calls.log"
case "$*" in
  "ad sp list --display-name "*) exit 0 ;;
  "ad sp create-for-rbac --name "*) n=$(grep -c create-for-rbac "$FAKE_STATE/calls.log")
     echo "{\"appId\": \"app-$n\", \"password\": \"pw-$n\"}"; exit 0 ;;
  "ad sp show --id "*|"ad app show --id "*) echo "oid-$4"; exit 0 ;;
  "account get-access-token "*) echo token; exit 0 ;;
  "keyvault secret set "*|"account set "*|"login "*) exit 0 ;;
esac
echo "unexpected az $*" >&2; exit 1
"""


def test_script_29_batch_runs_each_project_once_and_hands_the_range_to_29b(tmp_path):
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    for name, body in (("az", FAKE_AZ_PROJECT), ("curl", "#!/bin/bash\nexit 0\n")):
        (bin_dir / name).write_text(body, encoding="utf-8", newline="\n")
        (bin_dir / name).chmod(0o755)
    values = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_STATE": str(state),
              "TMPDIR": str(tmp_path), "KEY_VAULT_NAME": "kv-seeding", "SUBSCRIPTION_ID": "sub", "TENANT_ID": "tenant",
              "SKIP_LOGIN": "true", "SERVICE_PRINCIPAL_NAME_TEMPLATE": "esml-project[XXX]-sp",
              "PROJECT_NUMBER_XXX": "001", "PROJECT_NUMBER_TO": "003"}
    result = subprocess.run([BASH, str(PROJECT_SCRIPT)], input="Y\n", capture_output=True, text=True, env=values, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (state / "calls.log").read_text(encoding="utf-8")
    for nnn in ("001", "002", "003"):
        assert calls.count(f"ad sp create-for-rbac --name esml-project{nnn}-sp") == 1
        assert f"keyvault secret set --vault-name kv-seeding --name esml-project{nnn}-sp-secret" in calls
    assert "login" not in calls, "SKIP_LOGIN is honored"
    assert "mcp-api" not in calls, "the MCP API SPs are only created with ALSO_CREATE_MCP_API_SP=true"
