"""Offline tests only: no launcher, Git mutation, cloud CLI or deployment is run."""

import ast
import copy
import importlib.util
import json
import sys
import ctypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "bootstrap" / "lib" / "project_deployment.py"
spec = importlib.util.spec_from_file_location("project_deployment_contract", HELPER)
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)
GHA = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
ADO = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project"
SUBS = {env: str(index) * 8 + "-" + str(index) * 4 + "-" + str(index) * 4 + "-" + str(index) * 4 + "-" + str(index) * 12
        for index, env in enumerate(("dev", "stage", "prod"), 1)}
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def document():
    values = {
        "project_number_000": "017", "tenantId": TENANT,
        "dev_sub_id": SUBS["dev"], "test_sub_id": SUBS["stage"], "prod_sub_id": SUBS["prod"],
        "GITHUB_NEW_REPO": "org/consumer", "servicePrincipalSecret": "synthetic-secret-not-a-real-credential",
    }
    return {"dev": values, "stage_prod": copy.deepcopy(values)}


@pytest.fixture(autouse=True)
def no_real_commands(monkeypatch):
    monkeypatch.setattr(pd.subprocess, "run", Mock(side_effect=AssertionError("No real command is permitted")))
    monkeypatch.setattr(pd, "build_opener", Mock(side_effect=AssertionError("No HTTP transport is permitted")))


def instance(route):
    result = object.__new__(pd.Deployment)
    result.route = route
    result.selected = pd.validate_config(document(), "017", "stage")
    result.config = pd.canonical_json(document())
    result.repository = "org/consumer" if route == "gha" else "consumer"
    result.sleep = Mock()
    return result


@pytest.mark.parametrize("target", ["dev", "stage", "prod"])
def test_exact_target_identity_and_no_fallback(target):
    result = pd.validate_config(document(), "017", target)
    assert result["subscription"] == SUBS[target]
    broken = document()
    section = "dev" if target == "dev" else "stage_prod"
    del broken[section][{"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[target]]
    with pytest.raises(ValueError, match="no Dev fallback"):
        pd.validate_config(broken, "017", target)


@pytest.mark.parametrize("route", ["ADO", "GH"])
def test_update_launchers_refresh_main(route):
    script = (ROOT / "bootstrap" / f"{route}-update-aifactory-and-run-project.sh").read_text(encoding="utf-8")
    assert 'readonly SUBMODULE_BRANCH="main"' in script
    assert 'readonly SUBMODULE_BRANCH="release/v1.24"' not in script


@pytest.mark.parametrize("kind", ["project", "section", "tenant", "delete"])
def test_invalid_configuration_fails_before_commands(kind):
    data = document()
    if kind == "project":
        data["stage_prod"]["project_number_000"] = "018"
    elif kind == "section":
        del data["stage_prod"]
    elif kind == "tenant":
        data["stage_prod"]["tenantId"] = "<todo>"
    else:
        data["stage_prod"]["deleteAllForProject"] = True
    with pytest.raises(ValueError):
        pd.validate_config(data, "017", "stage")


@pytest.mark.parametrize("target,skip", [
    ("dev", ["Stage_GenAI_Project", "Prod_GenAI_Project"]),
    ("stage", ["Dev_GenAI_Project", "Prod_GenAI_Project"]),
    ("prod", ["Dev_GenAI_Project", "Stage_GenAI_Project"]),
])
def test_ado_request_is_exact_target_and_per_run_secret(target, skip):
    selected = pd.validate_config(document(), "017", target)
    encoded = pd.canonical_json(document())
    request = pd.run_request("main", encoded, selected)
    assert request["stagesToSkip"] == skip
    assert request["templateParameters"]["deploymentTarget"] == target
    assert request["templateParameters"]["deploymentProjectNumber"] == "017"
    assert request["variables"]["AIFACTORY_CONFIG_JSON"] == {"value": encoded, "isSecret": True}
    assert request["templateParameters"]["configFile"] == "aifactory/.reviewed-project-config.json"
    assert "servicePrincipalSecret" not in request["templateParameters"]["deploymentSettings"]


def test_ado_scheduling_uses_selected_project_not_other_loaded_export():
    config = document()
    config["stage_prod"].update(runNetworkingVar=False, BYO_subnets=True, useSelfHostedBuildAgent=True,
                               adminVMBuildAgentPool="reviewed-pool", adminVMBuildAgentName="reviewed-agent")
    selected = pd.validate_config(config, "017", "stage")
    settings = pd.run_request("main", pd.canonical_json(config), selected)["templateParameters"]["deploymentSettings"]
    assert settings["runNetworkingVar"] == "false" and settings["BYO_subnets"] == "true"
    assert settings["adminVMBuildAgentPool"] == "reviewed-pool"
    assert settings["adminVMBuildAgentName"] == "reviewed-agent"


def test_github_correlates_title_and_commit_not_recent_timestamp():
    intended = {"databaseId": 41, "displayTitle": "intended", "headSha": "a" * 40, "event": "workflow_dispatch"}
    other = {**intended, "databaseId": 99, "displayTitle": "unrelated"}
    assert pd.correlated_run([other, intended], "intended", "a" * 40) == "41"
    assert pd.correlated_run([intended], "intended", "b" * 40) is None
    with pytest.raises(ValueError, match="Multiple"):
        pd.correlated_run([intended, intended], "intended", "a" * 40)


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled"])
def test_github_dispatch_watches_exact_run_and_surfaces_failure(conclusion):
    deployment = instance("gha")
    calls = []
    payload = {}

    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[:2] == ["git", "rev-parse"]:
            return "a" * 40
        if argv[:2] == ["git", "ls-remote"]:
            return "a" * 40 + "\trefs/heads/main"
        if argv[:3] == ["gh", "workflow", "run"]:
            for i, value in enumerate(argv):
                if value == "--raw-field":
                    key, data = argv[i + 1].split("=", 1)
                    payload[key] = data
        return 0

    def read(argv):
        if argv[:3] == ["gh", "run", "list"]:
            return [
                {"databaseId": 99, "displayTitle": "unrelated external dispatch", "headSha": "a" * 40, "event": "workflow_dispatch"},
                {"databaseId": 42, "displayTitle": f"infra-project stage [{payload['deployment_id']}]",
                 "headSha": "a" * 40, "event": "workflow_dispatch"},
            ]
        assert argv[:4] == ["gh", "run", "view", "42"]
        return {"status": "completed", "conclusion": conclusion}

    deployment.command = command
    deployment.read_json = read
    if conclusion == "success":
        deployment.github()
    else:
        with pytest.raises(ValueError, match="failed or was cancelled"):
            deployment.github()
    assert payload["environment"] == "stage"
    assert payload["project_number"] == "017"
    assert payload["config_secret"].startswith("AIFACTORY_PROJECT_")
    assert any(argv[:4] == ["gh", "run", "watch", "42"] and "--exit-status" in argv for argv, _ in calls)
    assert any(argv[:3] == ["gh", "secret", "delete"] for argv, _ in calls)
    secret_call = next(kwargs for argv, kwargs in calls if argv[:3] == ["gh", "secret", "set"])
    assert secret_call["data"] == deployment.config
    assert all("synthetic-secret" not in " ".join(argv) for argv, _ in calls)


@pytest.mark.parametrize("result", ["succeeded", "failed", "canceled"])
def test_ado_uses_returned_run_id_and_watches_completion(result):
    deployment = instance("ado")
    calls = []

    def request(method, endpoint, body=None):
        calls.append((method, endpoint, body))
        if "/build/definitions?" in endpoint:
            return {"value": [{"id": 7, "repository": {"name": "consumer"},
                               "process": {"yamlFilename": pd.ADO_PIPELINE}}]}
        if method == "POST":
            return {"id": 53}
        assert endpoint == "/pipelines/7/runs/53?api-version=7.1"
        return {"state": "completed", "result": result}

    deployment.ado = request
    if result == "succeeded":
        deployment.azure_devops()
    else:
        with pytest.raises(ValueError, match="failed or was cancelled"):
            deployment.azure_devops()
    request_body = next(body for method, _, body in calls if method == "POST")
    assert request_body["templateParameters"]["deploymentTarget"] == "stage"


def test_refresh_preserves_selected_config_and_reviewed_templates(tmp_path):
    deployment = instance("gha")
    deployment.root = tmp_path / "consumer"
    deployment.state_dir = tmp_path / "state"
    deployment.state_dir.mkdir()
    deployment.root.mkdir()
    deployment.prompt = lambda _: "yes"
    deployment.templates = {}
    for relative in pd.FILES["gha"]:
        path = deployment.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reviewed", encoding="utf-8")
        deployment.templates[relative] = b"reviewed"
    config = deployment.root / "aifactory" / "variables.json"
    config.parent.mkdir()
    config.write_text("original-current-project", encoding="utf-8")
    (deployment.root / ".env").write_text("protected-env", encoding="utf-8")
    (deployment.state_dir / "GH-update-aifactory-and-run-project.sh").write_text("reviewed-launcher", encoding="utf-8")
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "bash":
            config.write_text("overwritten by refresh fixture", encoding="utf-8")
            for relative in deployment.templates:
                (deployment.root / relative).write_text("fetched-old-template", encoding="utf-8")
        if argv[:3] == ["git", "diff", "--cached"]:
            return ".github/workflows/infra-project.yml"
        return ""

    deployment.command = command
    deployment.update()
    assert config.read_text(encoding="utf-8") == "original-current-project"
    assert all((deployment.root / relative).read_bytes() == b"reviewed" for relative in deployment.templates)
    staged = next(argv for argv in calls if argv[:2] == ["git", "add"])
    assert "-A" not in staged and "aifactory/variables.json" not in staged and ".env" not in staged
    assert json.loads(deployment.config)["stage_prod"]["project_number_000"] == "017"


def test_github_unpublished_head_blocks_before_secret_or_dispatch():
    deployment = instance("gha")
    deployment.command = Mock(side_effect=["a" * 40, "b" * 40 + "\trefs/heads/main"])
    with pytest.raises(ValueError, match="published main"):
        deployment.github()
    assert all(call.args[0][0] == "git" for call in deployment.command.call_args_list)


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_prepare_validates_selected_export_templates_and_target_before_mutation(tmp_path, route):
    deployment = instance(route)
    deployment.root = tmp_path
    (tmp_path / ".git").mkdir()
    (tmp_path / "aifactory").mkdir()
    for relative in pd.FILES[route]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# " + pd.CONTRACT, encoding="utf-8")
    config = tmp_path / "aifactory" / "selected.json"
    config.write_text(json.dumps(document()), encoding="utf-8")
    origin = "https://github.com/org/consumer.git" if route == "gha" else "https://dev.azure.com/org/project/_git/consumer"
    deployment.command = Mock(side_effect=lambda argv, **kwargs: origin if argv[0] == "git" else 0)
    deployment.read_json = Mock(side_effect=lambda argv: {"id": 17} if argv[:2] == ["gh", "api"] else {
        "id": SUBS["stage"], "tenantId": TENANT, "user": {"name": "synthetic-test-owner"},
    })
    deployment.prepare("017", "stage", str(config))
    assert deployment.selected["subscription"] == SUBS["stage"]
    assert deployment.config == pd.canonical_json(document())
    deployment.command.reset_mock()
    deployment.read_json.reset_mock()
    invalid = document()
    invalid["stage_prod"]["test_sub_id"] = ""
    config.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="no Dev fallback"):
        deployment.prepare("017", "stage", str(config))
    deployment.command.assert_not_called()
    deployment.read_json.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Azure CLI command shim")
def test_windows_azure_cli_uses_bundled_python_not_batch_shell(tmp_path, monkeypatch):
    launcher = tmp_path / "wbin" / "az.cmd"
    launcher.parent.mkdir()
    launcher.write_text("synthetic not executed", encoding="utf-8")
    (tmp_path / "python.exe").write_text("synthetic not executed", encoding="utf-8")
    monkeypatch.setattr(pd.shutil, "which", lambda _: str(launcher))
    deployment = instance("ado")
    deployment.root = tmp_path
    deployment.environment = {}
    deployment.runner = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}"))
    assert deployment.command(["az", "account", "show"], capture=True) == "{}"
    args, options = deployment.runner.call_args
    assert args[0] == [str(tmp_path / "python.exe"), "-IBm", "azure.cli", "account", "show"]
    assert options["shell"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="Real current-user Windows DPAPI fixture")
def test_protected_config_decrypts_only_for_bound_factory_project_target(tmp_path):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    root = tmp_path / "consumer"
    (root / "aifactory").mkdir(parents=True)
    envelope = {"schema": 1, "folder": str(root / "aifactory"), "project": "017", "target": "stage", "document": document()}
    raw = json.dumps(envelope).encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.c_void_p))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    assert crypt.CryptProtectData(ctypes.byref(source), "synthetic offline fixture", None, None, None, 1, ctypes.byref(result))
    kernel = ctypes.WinDLL("kernel32")
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        sealed = ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)
    assert b"synthetic-secret" not in sealed
    path = tmp_path / "owned-plan.dpapi"
    path.write_bytes(sealed)
    assert pd.load_config(path, root, "017", "stage") == document()
    for folder, project, target in ((tmp_path / "other", "017", "stage"), (root, "018", "stage"), (root, "017", "prod")):
        with pytest.raises(ValueError, match="different factory/project/target"):
            pd.load_config(path, folder, project, target)
    path.write_bytes(b"corrupt ciphertext")
    with pytest.raises(ValueError, match="Cannot decrypt"):
        pd.load_config(path, root, "017", "stage")


def evaluate_condition(source, target, dev, stage="Skipped"):
    source = source.replace("'${{ parameters.deploymentTarget }}'", repr(target))
    source = source.replace("variables['Build.Reason']", "'Manual'")
    source = source.replace("dependencies.Dev_GenAI_Project.result", repr(dev))
    source = source.replace("dependencies.Stage_GenAI_Project.result", repr(stage))
    for old, new in (("and(", "both("), ("or(", "either("), ("not(", "negate(")):
        source = source.replace(old, new)
    functions = {"both": lambda *items: all(items), "either": lambda *items: any(items),
                 "eq": lambda a, b: a == b, "negate": lambda x: not x,
                 "succeeded": lambda: True, "canceled": lambda: False}

    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        return functions[node.func.id](*(visit(item) for item in node.args))

    return visit(ast.parse(source, mode="eval").body)


def test_ado_stage_only_preserves_genuine_failure_dependencies_and_legacy_flow():
    pipeline = yaml.safe_load((ADO / "infra-project-genai.yaml").read_text(encoding="utf-8"))
    dev, stage, prod = pipeline["stages"]
    assert not evaluate_condition(dev["condition"], "stage", "Skipped")
    assert evaluate_condition(stage["condition"], "stage", "Skipped")
    assert not evaluate_condition(stage["condition"], "stage", "Failed")
    assert not evaluate_condition(stage["condition"], "stage", "Canceled")
    assert evaluate_condition(stage["condition"], "", "Succeeded")
    assert not evaluate_condition(stage["condition"], "", "Skipped")
    assert evaluate_condition(prod["condition"], "prod", "Skipped", "Skipped")
    assert not evaluate_condition(prod["condition"], "prod", "Failed", "Skipped")
    assert not evaluate_condition(prod["condition"], "prod", "Skipped", "Failed")
    assert evaluate_condition(prod["condition"], "", "Succeeded", "Succeeded")
    for environment in pipeline["stages"]:
        for job in environment["jobs"]:
            steps = job["strategy"]["runOnce"]["deploy"]["steps"]
            protected = [step for step in steps if step.get("template", "").endswith("job-0-reviewed-project-config.yaml")]
            assert len(protected) == 2
            assert not protected[0]["parameters"].get("cleanup")
            assert protected[1]["parameters"]["cleanup"] is True
            assert steps[-1] == protected[1]
    assert stage["variables"]["dev_test_prod"] == "test"


def test_workflows_keep_legacy_defaults_and_forward_run_specific_secret():
    main = yaml.safe_load((GHA / "infra-project.yml").read_text(encoding="utf-8"))
    phase = yaml.safe_load((GHA / "infra-project-phase.yml").read_text(encoding="utf-8"))
    inputs = main.get("on", main.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["environment"]["default"] == "dev"
    assert inputs["config_secret"]["default"] == "AIFACTORY_CONFIG_JSON"
    assert "inputs.deployment_id" in main["run-name"]
    for job in ("deploy_infrastructure", "deploy_foundry"):
        assert main["jobs"][job]["with"]["config_secret"] == "${{ inputs.config_secret }}"
        assert main["jobs"][job]["with"]["config_hash"] == "${{ inputs.config_hash }}"
    assert phase["jobs"]["deploy-project"]["env"]["AIFACTORY_CONFIG_JSON"] == "${{ secrets[inputs.config_secret] }}"
    assert main["jobs"]["configure"]["steps"][-1]["name"] == "Remove run-specific reviewed configuration"
    assert phase["jobs"]["deploy-project"]["steps"][-1]["name"] == "Remove run-specific reviewed configuration"


def test_root_contract_is_opt_in_and_stable_helper_is_copied():
    for name in ("GH", "ADO"):
        source = (ROOT / "bootstrap" / f"{name}-update-aifactory-and-run-project.sh").read_text(encoding="utf-8")
        assert pd.CONTRACT in source
        assert 'reviewed_project=false' in source
        assert 'cp "$deployment_helper" "$state_dir/lib/project_deployment.py"' in source
        assert '"$helper_path" --route' in source
        assert 'helper_state_dir="$(cygpath -m "$helper_state_dir")"' in source
        assert "--project-only" in source
