"""Static contracts for additive, protected provider copies."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from unit.test_factory_lifecycle import workspace


ROOT = Path(__file__).resolve().parents[3]


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_templates_use_shared_runtime_and_never_interpolate_shell_expressions(provider):
    path = ROOT / "bootstrap/templates" / f"pipelines-only-{provider}.yml"
    text = path.read_text()
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    scripts = [node[key] for node in walk(parsed) for key in ("run", "bash", "inlineScript") if key in node]
    assert scripts
    assert all("${{" not in script for script in scripts)
    assert "pipeline_provider.py" in text and "prepare" in text and " finalize " in text
    assert "azure-enterprise-scale-ml" in text and "submodules:" in text
    assert "esaf-pipelines-execute" in text and "esaf-pipelines-prepare" in text
    assert "esaf-lifecycle-external" in text
    assert "--provider-context" in text and "--prepared" in text and "--parent-plan-hash" in text
    assert text.count("--download-input") == 3
    assert "install a trusted" not in text.lower()
    assert "persist-credentials: false" in text or "persistCredentials: false" in text
    for forbidden in ("azurefactory esaf", "localhost", "127.0.0.1", "az login --service-principal",
                      "0.0.0.0/0", "publicNetworkAccess", "submodule update --remote"):
        assert forbidden not in text


def test_github_oidc_and_actual_review_precede_execute():
    pipeline = yaml.load((ROOT / "bootstrap/templates/pipelines-only-gha.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(pipeline["on"]) == {"workflow_dispatch"}
    assert "request_path" in pipeline["on"]["workflow_dispatch"]["inputs"]
    assert pipeline["jobs"]["execute"]["needs"] == "prepare"
    assert pipeline["jobs"]["finalize"]["needs"] == ["prepare", "execute"]
    assert "always()" in pipeline["jobs"]["finalize"]["if"]
    assert not any(step.get("uses") == "actions/upload-artifact@v4"
                   for step in pipeline["jobs"]["execute"]["steps"])
    for key in ("prepare", "execute", "finalize"):
        job = pipeline["jobs"][key]
        assert job["permissions"]["id-token"] == "write"
        assert job["environment"].startswith("esaf-pipelines-")
        assert job["env"]["AZURE_CONFIG_DIR"].endswith(("-prepare", "-execute", "-finalize"))
        assert any(step.get("uses") == "azure/login@v2" for step in job["steps"])
    artifacts = [step["with"]["path"] for job in pipeline["jobs"].values() for step in job["steps"]
                 if step.get("uses") == "actions/upload-artifact@v4"]
    assert artifacts == [".esaf/context.json\n.esaf/prepared.json\n", ".esaf/receipt.json"]
    lifecycle = [step for job in pipeline["jobs"].values() for step in job["steps"]
                 if "pipeline_credentials.py" in step.get("run", "")]
    assert len(lifecycle) == 3
    for step in lifecycle:
        assert step["env"]["GH_TOKEN"] == "${{ secrets.ESAF_PROVIDER_TOKEN }}"
        assert "pipeline_credentials.py --provider gha --" in step["run"]
    assert all(job["env"]["GH_TOKEN"] == "${{ github.token }}" for job in pipeline["jobs"].values())


def test_ado_scoped_federated_connection_and_no_success_on_partial():
    pipeline = yaml.load((ROOT / "bootstrap/templates/pipelines-only-ado.yml").read_text(), Loader=yaml.BaseLoader)
    assert pipeline["trigger"] == "none" and pipeline["pr"] == "none"
    assert pipeline["stages"][1]["dependsOn"] == "Prepare"
    assert pipeline["stages"][2]["dependsOn"] == "Review"
    assert pipeline["stages"][3]["stage"] == "Finalize"
    assert pipeline["stages"][3]["dependsOn"] == ["Prepare", "Execute"]
    review_job = pipeline["stages"][1]["jobs"][0]
    assert review_job["pool"] == "server"
    review = review_job["steps"][0]
    assert review["task"] == "ManualValidation@1"
    assert review["name"] == review["displayName"] == "ReviewPipelinesLifecycle"
    assert review["inputs"]["allowApproversToApproveTheirOwnRuns"] == "false"
    assert review["inputs"]["onTimeout"] == "reject"
    assert "esaf-pipelines-reviewers" in review["inputs"]["approvers"]
    assert "$(operation_id)" in review["inputs"]["instructions"]
    assert "$(plan_hash)" in review["inputs"]["instructions"]
    cli = [node for node in walk(pipeline) if node.get("task") == "AzureCLI@2"]
    assert len(cli) == 3
    for node in cli:
        assert node["inputs"]["azureSubscription"] == "esaf-pipelines-workload-identity"
        assert node["inputs"]["useGlobalConfig"] == "false"
        assert node["inputs"]["addSpnToEnvironment"] == "false"


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_seeded_credentials_only_reach_post_login_lifecycle_steps(provider):
    text = (ROOT / "bootstrap/templates" / f"pipelines-only-{provider}.yml").read_text()
    pipeline = yaml.load(text, Loader=yaml.BaseLoader)
    nodes = list(walk(pipeline))
    if provider == "gha":
        for job in pipeline["jobs"].values():
            steps = job["steps"]
            if job.get("name") == "complete":
                assert not any("pipeline_credentials.py" in step.get("run", "") for step in steps)
                continue
            login = next(index for index, step in enumerate(steps) if step.get("uses") == "azure/login@v2")
            consumers = [index for index, step in enumerate(steps) if "pipeline_credentials.py" in step.get("run", "")]
            assert len(consumers) == 1 and consumers[0] > login
        consumers = [node for node in nodes if "pipeline_credentials.py" in node.get("run", "")]
    else:
        consumers = [node for node in nodes if node.get("task") == "AzureCLI@2"]
        assert all("pipeline_credentials.py --provider ado --" in node["inputs"]["inlineScript"]
                   for node in consumers)
        assert all("pipeline_credentials.py" not in node.get("bash", "") for node in nodes)
    assert len(consumers) == 3
    for step in consumers:
        assert "ESAF_PROVIDER_CREDENTIAL_SOURCE" in step["env"]
        assert "ESAF_PROVIDER_TOKEN_SECRET_ID" in step["env"]
    for node in nodes:
        if "--download-input" in node.get("run", "") or "--download-input" in node.get("bash", ""):
            assert "ESAF_PROVIDER_TOKEN_SECRET_ID" not in node.get("env", {})
            assert "pipeline_credentials.py" not in node.get("run", node.get("bash", ""))
    assert "GITHUB_ENV" not in text and "task.setsecret" not in text
    assert "--env-file" not in text


def test_ado_prepared_artifact_has_an_explicit_nonsecret_allowlist():
    pipeline = yaml.load((ROOT / "bootstrap/templates/pipelines-only-ado.yml").read_text(), Loader=yaml.BaseLoader)
    publish = [node for node in walk(pipeline) if node.get("task") == "PublishPipelineArtifact@1"]
    assert publish[0]["inputs"]["targetPath"] == ".esaf/prepared-artifact"
    text = (ROOT / "bootstrap/templates/pipelines-only-ado.yml").read_text()
    assert 'for name in ("context.json", "prepared.json"):' in text


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_continuations_keep_fixed_native_jobs_and_only_provider_controlled_dispatch(provider):
    text = (ROOT / "bootstrap/templates" / f"pipelines-only-{provider}.yml").read_text()
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    if provider == "gha":
        assert set(parsed["jobs"]) == {"prepare", "execute", "finalize", "complete"}
        parameters = parsed["on"]["workflow_dispatch"]["inputs"]
    else:
        assert [stage["stage"] for stage in parsed["stages"]] == ["Prepare", "Review", "Execute", "Finalize", "Complete"]
        parameters = {parameter["name"]: parameter for parameter in parsed["parameters"]}
    assert parameters["parent_operation_id"]["default"] == parameters["parent_plan_hash"]["default"] == ""
    assert parameters["recovery_operation_id"]["default"] == parameters["recovery_plan_hash"]["default"] == ""
    assert len(parameters) <= 10
    assert "--parent-operation-id" in text and "--parent-plan-hash" in text
    assert "--recovery-operation-id" in text and "--recovery-plan-hash" in text
    helper = (ROOT / "bootstrap/lib/pipeline_provider.py").read_text()
    assert "pipeline_lifecycle.py" in helper and '"prepare-continuation"' in helper
    assert '"prepare-recovery"' in helper
    assert '"--expected-plan-hash"' in helper and "verify_finalizer" in helper
    assert 'args.command == "finalize" and receipt["status"] == "continuation-required"' in helper
    assert "approved" not in parameters and "approval" not in parameters


def test_bash_validates_locally_before_exec_dispatch():
    script = (ROOT / "bootstrap/ESAF-pipelines.sh").read_text()
    assert script.index("--validate-only") < script.index('exec "$python_bin"')
    assert '"$@"' in script and "eval " not in script
    assert all(word not in script for word in ("curl", "az ", "azurefactory", "localhost"))


def test_real_bash_invalid_input_returns_nonzero_before_provider_access():
    bash = (str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe")
            if os.name == "nt" else shutil.which("bash"))
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash is not installed")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GH_TOKEN", "GITHUB_TOKEN", "SYSTEM_ACCESSTOKEN", "AZURE_DEVOPS_EXT_PAT"}}
    environment["PYTHON"] = sys.executable
    result = subprocess.run([bash, str(ROOT / "bootstrap/ESAF-pipelines.sh"),
                             "--request", "does-not-exist-provider-contract.json"],
                            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30, shell=False)
    assert result.returncode == 2, result.stderr
    assert "not-completed" in result.stderr
    assert "dispatching" not in result.stderr


@pytest.mark.parametrize("joined", [False, True])
def test_real_bash_explicit_consumer_root_does_not_require_git_in_caller_directory(joined):
    bash = (str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe")
            if os.name == "nt" else shutil.which("bash"))
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash is not installed")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GH_TOKEN", "GITHUB_TOKEN", "SYSTEM_ACCESSTOKEN", "AZURE_DEVOPS_EXT_PAT"}}
    environment.update(PYTHON=sys.executable, GIT_CEILING_DIRECTORIES=str(ROOT))
    selected = ["--repo-root=" + str(ROOT)] if joined else ["--repo-root", str(ROOT)]
    result = subprocess.run([bash, str(ROOT / "bootstrap/ESAF-pipelines.sh"), *selected,
                             "--request", "does-not-exist-provider-contract.json"],
                            cwd=ROOT / "bootstrap", env=environment, capture_output=True, text=True,
                            timeout=30, shell=False)
    assert result.returncode == 2, result.stderr
    assert "not-completed" in result.stderr and "not a git repository" not in result.stderr
    assert "dispatching" not in result.stderr


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_real_bash_custom_root_and_local_env_reach_all_validation_phases(workspace, provider):
    from unit.test_pipeline_inputs import register, request, save
    bash = (str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe")
            if os.name == "nt" else shutil.which("bash"))
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash is not installed")
    save(workspace, register(provider))
    (workspace / "request.json").write_text(json.dumps(request(3, provider) | {"provider_binding": "provider.json"}))
    (workspace / "provider.json").write_text(json.dumps({
        "schema": 1, "provider": provider, "consumer_ref": "refs/heads/main",
        "repository": "https://github.com/acme/factory" if provider == "gha"
        else "https://dev.azure.com/acme/project/_git/factory"}))
    local_env = workspace / ".env"
    local_env.write_text(("GH_TOKEN" if provider == "gha" else "SYSTEM_ACCESSTOKEN") + "=offline-not-a-real-token\n")
    environment = {key: value for key, value in os.environ.items() if key not in {
        "GH_TOKEN", "GITHUB_TOKEN", "SYSTEM_ACCESSTOKEN", "AZURE_DEVOPS_EXT_PAT", "GITHUB_ACTIONS", "TF_BUILD"}}
    environment["PYTHON"] = sys.executable
    result = subprocess.run([bash, str(ROOT / "bootstrap/ESAF-pipelines.sh"), "--repo-root", str(workspace),
                             "--request", "request.json", "--env-file", str(local_env), "--validate-only"],
                            cwd=ROOT / "bootstrap", env=environment, capture_output=True, text=True,
                            timeout=30, shell=False)
    assert result.returncode == 0, result.stderr
    outputs = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(outputs) == 3 and outputs[1]["valid"] is outputs[2]["valid"] is True
    assert "offline-not-a-real-token" not in result.stdout + result.stderr
    assert "dispatching" not in result.stderr
