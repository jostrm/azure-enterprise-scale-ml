"""Offline checks for the update launcher's JSON producer and pipeline consumer."""

import copy
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = ROOT / "bootstrap" / "GH-update-aifactory-and-run-project.sh"
IDENTITY = {
    "GITHUB_USERNAME": "example",
    "GITHUB_USE_SSH": "true",
    "GITHUB_TEMPLATE_REPO": "example/template",
    "GITHUB_NEW_REPO": "example/new-repo",
    "GITHUB_NEW_REPO_VISIBILITY": "private",
}


@pytest.fixture
def github_environments(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "bootstrap" / "lib"))
    import github_environments
    return github_environments


def test_new_github_environments_are_canonical(github_environments):
    assert github_environments.resolve([]) == {"dev": "Dev", "stage": "Stage", "prod": "Prod"}


def test_existing_github_environment_case_is_preserved(github_environments):
    assert github_environments.resolve(["dev", "Stage", "PROD"]) == {
        "dev": "dev", "stage": "Stage", "prod": "PROD"}


def test_named_github_bindings_do_not_require_enrollment_for_bootstrap(github_environments):
    assert github_environments.resolve(["aifactory-existing"]) == github_environments.DEFAULTS
    mapping = {"dev": "aifactory-existing", "stage": "Stage", "prod": "Prod"}
    assert github_environments.resolve(["aifactory-existing"], requested=mapping) == mapping
    assert github_environments.resolve(["aifactory-existing"], saved=mapping) == mapping


@pytest.mark.parametrize("saved,requested,names", [
    ({"dev": "dev", "stage": "stage", "prod": "prod"},
     {"dev": "Dev", "stage": "Stage", "prod": "Prod"}, ["dev"]),
    ({"dev": "Dev", "stage": "Stage", "prod": "Prod"}, None, ["dev"]),
    (None, {"dev": "Dev", "stage": "Dev", "prod": "Prod"}, []),
    (None, {"dev": "Dev"}, []),
])
def test_github_environment_migration_never_happens_implicitly(github_environments, saved, requested, names):
    with pytest.raises(github_environments.EnrollmentError):
        github_environments.resolve(names, saved, requested)


def test_github_environment_mapping_is_persisted_and_verified(github_environments):
    class Cloud:
        read_only = True
        variable = None

        def command(self, args):
            assert args[-1].endswith("/environments?per_page=100")
            return '[{"environments":[{"name":"dev"}]}]'

        def gh(self, method, endpoint, body=None, allowed=()):
            if method == "GET":
                return (200, {}, {"value": self.variable}) if self.variable else (404, {}, None)
            assert method == "POST"
            assert endpoint.endswith("/actions/variables")
            assert body["name"] == github_environments.VARIABLE
            self.variable = body["value"]
            return 201, {}, None

    class Repository:
        config = {"github_repository": "example/factory"}
        cloud = Cloud()
        calls = []
        def environment(self, name):
            return {"name": "dev", "protection_rules": ["keep"]} if name == "dev" else None
        def ensure_environment(self, name, expected):
            self.calls.append((name, expected))
            return expected or {"name": name}

    repository = Repository()
    mapping = github_environments.ensure(repository, ["dev", "stage", "prod"])
    assert mapping == {"dev": "dev", "stage": "Stage", "prod": "Prod"}
    assert repository.calls[0] == ("dev", {"name": "dev", "protection_rules": ["keep"]})
    assert json.loads(repository.cloud.variable) == mapping


@pytest.mark.parametrize("mode", ["existing", "raced", "absent", "changed", "error", "unverified"])
def test_environment_creation_preserves_protection_and_verifies_graphql(github_environments, mode):
    name = "Team: Dev/blue"
    protected = {"name": name, "node_id": "environment-node", "protection_rules": ["keep"]}
    calls = []

    class Cloud:
        read_only = True
        created = False

        def gh(self, method, endpoint, body=None, allowed=()):
            calls.append((method, endpoint))
            assert method == "GET"
            if endpoint.endswith("/environments/Team%3A%20Dev%2Fblue"):
                if mode in ("existing", "raced", "changed") or self.created:
                    value = dict(protected)
                    if mode == "changed":
                        value["protection_rules"] = ["different"]
                    if mode == "unverified":
                        value["node_id"] = "different"
                    return 200, {}, value
                return 404, {}, None
            assert endpoint == "repos/example/factory"
            return 200, {}, {"node_id": "repository-node"}

        def command(self, args, data):
            assert args == ["gh", "api", "--hostname", "github.com", "--method", "POST",
                            "graphql", "--input", "-"]
            payload = json.loads(data)
            assert payload["variables"] == {"repository": "repository-node", "name": name}
            assert "createEnvironment" in payload["query"]
            calls.append(("POST", "graphql"))
            self.created = True
            return json.dumps({"errors": ["denied"]} if mode == "error" else {
                "data": {"createEnvironment": {"environment": {"id": "environment-node", "name": name}}}})

    repository = github_environments.Repository("example/factory")
    repository.cloud = Cloud()
    expected = protected if mode in ("existing", "changed") else None
    if mode in ("changed", "error", "unverified"):
        with pytest.raises(github_environments.EnrollmentError):
            repository.ensure_environment(name, expected)
    else:
        assert repository.ensure_environment(name, expected) == protected
    assert calls.count(("POST", "graphql")) == int(mode in ("absent", "error", "unverified"))


def test_environment_helper_needs_no_registered_factory_modules(tmp_path):
    for name in ("github_environments.py", "factory_enrollment.py"):
        shutil.copyfile(ROOT / "bootstrap/lib" / name, tmp_path / name)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run([sys.executable, str(tmp_path / "github_environments.py"), "--help"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--ensure" in result.stdout


def test_github_workflow_jobs_use_mapping_not_azure_environment_selector():
    templates = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
    for name in ("infra-common.yml", "infra-project.yml", "infra-project-phase.yml",
                 "infra-project-dashboards.yml", "infra-ai-gateway.yml"):
        document = yaml.safe_load((templates / name).read_text(encoding="utf-8"))
        environments = [job["environment"] for job in document["jobs"].values() if "environment" in job]
        assert environments, name
        assert all("vars.AIFACTORY_GITHUB_ENVIRONMENTS" in value for value in environments), name

MARKER = (
    '"${PYTHON[@]}" - "$CONFIG_FILE" "$CONFIG_TEMPLATE_FILE" "$RUNNER_LABEL" '
    '"$state_dir/current.env" <<\'PY\'\n'
)


@pytest.mark.parametrize("has_env", [True, False])
def test_inline_merge_backfills_only_missing_github_identity(tmp_path, monkeypatch, has_env):
    launcher = LAUNCHER
    # Execute only the Python merge block, never any shell command or launcher.
    code = launcher.read_text(encoding="utf-8").split(MARKER, 1)[1].split("\nPY", 1)[0]
    active = {
        "dev": {
            "projectPrefix": "", "projectSuffix": "",
            "GITHUB_NEW_REPO": "explicit/keep",
            "GITHUB_USERNAME": "",
            "unmapped": {"keep": [False, 0, ""]},
        },
        "stage_prod": {"projectPrefix": "", "projectSuffix": "", "stage_only": "keep"},
        "extra_section": {"untouched": True},
        "_wizard": {"custom": "keep"},
    }
    original = copy.deepcopy(active)
    template = {
        "dev": {
            "projectPrefix": "esml-", "projectSuffix": "-rg",
            "GITHUB_USERNAME": "", "GITHUB_USE_SSH": "false",
            "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
            "GITHUB_NEW_REPO": "", "GITHUB_NEW_REPO_VISIBILITY": "public",
        },
    }
    active_path = tmp_path / "active.json"
    template_path = tmp_path / "template.json"
    env_path = tmp_path / "current.env"
    active_path.write_text(json.dumps(active), encoding="utf-8")
    template_path.write_text(json.dumps(template), encoding="utf-8")
    if has_env:
        env_path.write_text(
            "\n".join(f"export {key}='{value}' # comment" for key, value in IDENTITY.items())
            + "\nGITHUB_TOKEN=do-not-copy\nAZURE_CLIENT_SECRET=do-not-copy\n",
            encoding="utf-8-sig",
        )
    before = {path: path.read_bytes() for path in (template_path, env_path) if path.exists()}
    monkeypatch.setattr("sys.argv", ["merge", str(active_path), str(template_path), "unit-runner", str(env_path)])
    exec(compile(code, str(launcher), "exec"), {"__name__": "__main__"})
    result = json.loads(active_path.read_text(encoding="utf-8"))
    for section in ("dev", "stage_prod"):
        for key, value in original[section].items():
            assert result[section][key] == value
        for key in IDENTITY:
            if key not in original[section]:
                assert result[section][key] == (
                    IDENTITY[key] if has_env else template["dev"][key]
                )
    assert result["extra_section"] == original["extra_section"]
    assert result["_wizard"] == {"custom": "keep", "orchestrator": "gha"}
    assert result["dev"]["selfHostedRunnerLabel"] == "unit-runner"
    assert result["dev"]["useSelfHostedBuildAgent"] == "true"
    assert all(path.read_bytes() == value for path, value in before.items())
    assert "do-not-copy" not in active_path.read_text(encoding="utf-8")


def test_source_template_contains_only_generic_github_identity():
    template_path = ROOT / "environment_setup" / "aifactory" / "variables.json"
    values = json.loads(template_path.read_text(encoding="utf-8"))["dev"]
    assert {key: values[key] for key in IDENTITY} == {
        "GITHUB_USERNAME": "",
        "GITHUB_USE_SSH": "false",
        "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
        "GITHUB_NEW_REPO": "",
        "GITHUB_NEW_REPO_VISIBILITY": "public",
    }
    assert "_wizard" not in values


def test_all_canonical_templates_include_default_false_hub_intent():
    base = ROOT / "environment_setup" / "aifactory"
    document = json.loads((base / "variables.json").read_text(encoding="utf-8"))
    assert set(document) == {"dev"}
    assert document["dev"]["enableAIFactoryHub"] is False
    assert document["dev"]["centralDnsZoneByPolicyInHub"] is False
    templates = base / "bicep" / "copy_to_local_settings"
    yaml_text = (templates / "azure-devops" / "esml-yaml-pipelines" /
                 "variables" / "variables.yaml").read_text(encoding="utf-8")
    env_text = (templates / "github-actions" / ".env.template").read_text(encoding="utf-8")
    upload = (templates / "github-actions" /
              "03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    for key, env_key in (("enableAIFactoryHub", "ENABLE_AI_FACTORY_HUB"),
                         ("centralDnsZoneByPolicyInHub", "CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB")):
        assert re.search(r"^\s+" + key + r': "false"', yaml_text, re.M)
        assert re.search(r"^" + env_key + r'="false"', env_text, re.M)
        assert f'"{env_key}"' in upload


def test_json_override_consumer_defers_annotations_for_python_39():
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    source = path.read_text(encoding="utf-8")
    assert "from __future__ import annotations" in source.splitlines()[:10]


def test_pipeline_consumer_ignores_wizard_metadata_and_reserved_github_identity(tmp_path, monkeypatch):
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("json_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values, section = module.selected_values({
        "dev": {"projectPrefix": "", **IDENTITY},
        "_wizard": {"orchestrator": "gha"},
    }, "dev")
    assert section == "dev"
    assert "_wizard" not in values
    github_env = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    applied, skipped = module.apply(values, "github", None)
    assert applied == 1
    assert set(skipped) == set(IDENTITY)
    assert "projectPrefix<<" in github_env.read_text(encoding="utf-8")
    assert "GITHUB_" not in github_env.read_text(encoding="utf-8")


@pytest.fixture
def json_override_module():
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("dashboard_json_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("dns,own", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
@pytest.mark.parametrize("environment,section", [("dev", "dev"), ("prod", "stage_prod")])
def test_hub_pair_uses_existing_camel_keys_without_dropping_flags(
        json_override_module, tmp_path, monkeypatch, capsys, dns, own,
        pipeline_format, environment, section):
    original = {section: {"centralDnsZoneByPolicyInHub": dns, "enableAIFactoryHub": own}}
    config = copy.deepcopy(original)
    values, selected = json_override_module.selected_values(config, environment)
    assert selected == section
    assert values == {key: str(value).lower() for key, value in original[section].items()}
    output = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    applied, skipped = json_override_module.apply(values, pipeline_format, None)
    assert applied == 2 and skipped == []
    text = output.read_text(encoding="utf-8") if pipeline_format == "github" else capsys.readouterr().out
    for key, value in original[section].items():
        if pipeline_format == "github":
            assert f"{key}<<" in text
            assert f"\n{str(value).lower()}\n" in text
        else:
            assert f"##vso[task.setvariable variable={key}]{str(value).lower()}" in text
    assert config == original


@pytest.mark.parametrize("value", ["", "https://portal.azure.com/#dashboard/private/example"])
@pytest.mark.parametrize("environment,section", [("dev", "dev"), ("stage", "stage_prod"), ("prod", "stage_prod")])
def test_dashboard_config_key_maps_to_existing_shell_safe_name(json_override_module, value, environment, section):
    values, selected = json_override_module.selected_values({
        section: {"aifactory-dash-01": value, "projectPrefix": ""},
    }, environment)
    assert selected == section
    assert values == {"AIFACTORY_DASHBOARD_URL": value, "projectPrefix": ""}


@pytest.mark.parametrize("names", [
    ["aifactory-dash-01", "AIFACTORY_DASHBOARD_URL"],
    ["AIFACTORY_DASHBOARD_URL", "aifactory-dash-01"],
])
def test_conflicting_aliases_fail_without_printing_values(json_override_module, capsys, names):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {
            names[0]: "private-value-a", names[1]: "private-value-b",
        }}, "dev")
    error = capsys.readouterr().err
    assert "Conflicting configuration values" in error
    assert "private-value" not in error
    values, _ = json_override_module.selected_values({"dev": dict.fromkeys(names, "")}, "dev")
    assert values == {"AIFACTORY_DASHBOARD_URL": ""}


@pytest.mark.parametrize("name", [
    "other-hyphen", "x\nINJECTED", "x;echo", "1invalid",
    "org-department-other", "org-department-name\nINJECTED", "org-department-id;echo",
])
def test_dashboard_alias_does_not_relax_variable_name_validation(json_override_module, name):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {name: "value"}}, "dev")


@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
@pytest.mark.parametrize("environment,section", [
    ("dev", "dev"), ("stage", "stage_prod"), ("test", "stage_prod"), ("prod", "stage_prod"),
])
@pytest.mark.parametrize("metadata", [
    {"org-department-name": "", "org-department-id": ""},
    {"org-department-name": '研发 O\'Brien "A" $HOME $(noop) `noop`', "org-department-id": "部门/0007-α"},
])
def test_project_organization_metadata_is_not_exported(
        json_override_module, tmp_path, monkeypatch, capsys, pipeline_format,
        environment, section, metadata):
    original = {section: {**metadata, "projectPrefix": "", "enableAIFactoryHub": False},
                "_wizard": {"orchestrator": "gha"}}
    config = copy.deepcopy(original)
    values, selected = json_override_module.selected_values(config, environment)
    assert selected == section
    assert values == {"projectPrefix": "", "enableAIFactoryHub": "false"}
    output = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    applied, skipped = json_override_module.apply(values, pipeline_format, None)
    assert applied == 2 and skipped == []
    captured = capsys.readouterr()
    text = captured.out + captured.err
    if pipeline_format == "github":
        text += output.read_text(encoding="utf-8")
    for key, value in metadata.items():
        assert key not in text
        if value:
            assert value not in text
    assert "ORG_DEPARTMENT_" not in text
    assert config == original


@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
@pytest.mark.parametrize("deployment_environment", ["dev", "stage", "test", "prod"])
def test_full_canonical_template_applies_with_dashboard_key_offline(tmp_path, pipeline_format, deployment_environment):
    consumer = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    template = ROOT / "environment_setup" / "aifactory" / "variables.json"
    original = template.read_bytes()
    environment = os.environ.copy()
    github_env = tmp_path / "github-env"
    environment["GITHUB_ENV"] = str(github_env)
    result = subprocess.run(
        [sys.executable, str(consumer), "--file", str(template), "--environment", deployment_environment,
         "--format", pipeline_format],
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Applied " in result.stdout
    output = (github_env.read_text(encoding="utf-8") if pipeline_format == "github" else "") + result.stdout
    assert "org-department-" not in output
    assert "ORG_DEPARTMENT_" not in output
    if pipeline_format == "github":
        assert "AIFACTORY_DASHBOARD_URL<<" in github_env.read_text(encoding="utf-8")
        assert "SCALING_MODE<<" in github_env.read_text(encoding="utf-8")
        assert "\nshared-subscriptions\n" in github_env.read_text(encoding="utf-8")
        assert "scaling-mode<<" not in github_env.read_text(encoding="utf-8")
    else:
        assert "##vso[task.setvariable variable=AIFACTORY_DASHBOARD_URL]" in result.stdout
        assert "##vso[task.setvariable variable=SCALING_MODE]shared-subscriptions" in result.stdout
        assert "variable=scaling-mode" not in result.stdout
    assert template.read_bytes() == original


@pytest.mark.parametrize("mode", ["own-subscriptions", "shared-subscriptions"])
@pytest.mark.parametrize("environment,section", [
    ("dev", "dev"), ("stage", "stage_prod"), ("test", "stage_prod"), ("prod", "stage_prod"),
])
@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
def test_full_template_scaling_mode_alias(json_override_module, tmp_path, monkeypatch, capsys,
                                        mode, environment, section, pipeline_format):
    template = ROOT / "environment_setup" / "aifactory" / "variables.json"
    config = json.loads(template.read_text(encoding="utf-8"))
    config[section] = {**config["dev"], "scaling-mode": mode}
    values, selected = json_override_module.selected_values(config, environment)
    assert selected == section
    assert values["SCALING_MODE"] == mode
    assert "scaling-mode" not in values
    assert values["common_vnet_cidr"] == config[section]["common_vnet_cidr"]
    output = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    json_override_module.apply(values, pipeline_format, None)
    if pipeline_format == "github":
        text = output.read_text(encoding="utf-8")
        assert "SCALING_MODE<<" in text
        assert f"\n{mode}\n" in text
    else:
        assert f"##vso[task.setvariable variable=SCALING_MODE]{mode}" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["scaling-mode", "SCALING_MODE"])
@pytest.mark.parametrize("value", ["", "own", "shared", "Own-subscriptions",
                                  " own-subscriptions", "shared-subscriptions\n",
                                  None, True, 1, [], {}])
def test_invalid_scaling_modes_are_rejected(json_override_module, name, value):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {name: value}}, "dev")


@pytest.mark.parametrize("names", [
    ("scaling-mode", "SCALING_MODE"), ("SCALING_MODE", "scaling-mode"),
])
def test_scaling_alias_conflicts_are_rejected(json_override_module, capsys, names):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {
            names[0]: "own-subscriptions", names[1]: "shared-subscriptions",
        }}, "dev")
    assert "Conflicting configuration values" in capsys.readouterr().err
    values, _ = json_override_module.selected_values({
        "dev": dict.fromkeys(names, "own-subscriptions"),
    }, "dev")
    assert values == {"SCALING_MODE": "own-subscriptions"}


def test_canonical_scaling_templates_and_github_upload_use_safe_names():
    templates = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
    env_text = (templates / "github-actions/.env.template").read_text(encoding="utf-8")
    yaml_text = (templates / "azure-devops/esml-yaml-pipelines/variables/variables.yaml").read_text(encoding="utf-8")
    upload_text = (templates / "github-actions/03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    assert re.search(r'^SCALING_MODE="shared-subscriptions"', env_text, re.MULTILINE)
    assert re.search(r'^  scaling-mode: "shared-subscriptions"', yaml_text, re.MULTILINE)
    assert '"SCALING_MODE"' in upload_text.split("repo_level_vars=(", 1)[1].split("\n)", 1)[0]


@pytest.mark.parametrize("current_mode", [None, "own-subscriptions", "shared-subscriptions"])
def test_update_env_backfills_scaling_mode_without_overwriting_user_value(tmp_path, monkeypatch,
                                                                          current_mode):
    marker = '"${PYTHON[@]}" - ".env" ".env.template" "$RUNNER_LABEL" <<\'PY\'\n'
    code = LAUNCHER.read_text(encoding="utf-8").split(marker, 1)[1].split("\nPY", 1)[0]
    active = tmp_path / "active.env"
    template = tmp_path / "template.env"
    active.write_text(
        f'SCALING_MODE="{current_mode}"\n' if current_mode is not None else "",
        encoding="utf-8",
    )
    source = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template"
    template.write_bytes(source.read_bytes())
    original = active.read_bytes()
    monkeypatch.setattr("sys.argv", ["merge", str(active), str(template), "unit-runner"])
    exec(compile(code, str(LAUNCHER), "exec"), {"__name__": "__main__"})
    assert f'SCALING_MODE="{current_mode or "shared-subscriptions"}"' in template.read_text(encoding="utf-8")
    assert active.read_bytes() == original


@pytest.mark.parametrize("cidr,octet", [
    ("172.16.XX.0/20", "0"),
    ("172.16.XX.0/20", "16"),
    ("172.16.XX.0/20", "32"),
    ("172.16.0.0/18", "15"),
    ("172.16.0.0/18", "20"),
    ("172.16.0.0/18", "25"),
    ("172.16.0.0/16", "61"),
])
def test_preflight_substitutes_vnet_and_subnet_templates_offline(bash_executable, cidr, octet):
    preflight = ROOT / "environment_setup/aifactory/bicep/scripts/preflight.sh"
    text = preflight.read_text(encoding="utf-8")
    substitution = re.search(r"(?m)^sub_xx\(\).*?$", text).group(0)
    validation = text.split("  local out _cidr_data\n", 1)[1].split('  local had=""', 1)[0]
    script = (
        "set -euo pipefail\n" + substitution + "\nvalidate() {\n" + validation +
        '\nprintf "%s" "$out"\n}\nvalidate\n'
    )
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"BASH_ENV", "ENV", "SHELLOPTS"}}
    environment.update({
        "PYBIN": Path(sys.executable).as_posix(),
        "COMMON_VNET_CIDR": cidr,
        "DEV_CIDR_RANGE": octet,
        # These fixtures validate one configured environment, including fixed VNets.
        "TEST_CIDR_RANGE": "",
        "PROD_CIDR_RANGE": "",
        "COMMON_SUBNET_CIDR": "172.16.XX.0/26",
        "COMMON_SUBNET_SCORING_CIDR": "172.16.XX.64/26",
        "COMMON_PBI_SUBNET_CIDR": "172.16.XX.128/26",
        "COMMON_BASTION_SUBNET_CIDR": "172.16.XX.192/26",
    })
    result = subprocess.run(
        [bash_executable, "--noprofile", "--norc", "-c", script],
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("current_mode", [None, "own-subscriptions", "shared-subscriptions"])
def test_scaleset_template_merge_preserves_mode_in_all_formats(tmp_path, current_mode):
    helper = ROOT / "bootstrap/lib/aifactory_scaleset_config.py"
    spec = importlib.util.spec_from_file_location("scaling_bootstrap_config", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    formats = {
        "env": ('SCALING_MODE="{}"\n', module.merge_env_template),
        "yaml": ('variables:\n  scaling-mode: "{}"\n', module.merge_yaml_template),
        "json": ('{{"dev":{{"scaling-mode":"{}"}}}}', module.merge_json_template),
    }
    for extension, (pattern, merge) in formats.items():
        active = tmp_path / f"active.{extension}"
        template = tmp_path / f"template.{extension}"
        empty = '{"dev":{}}' if extension == "json" else "variables:\n" if extension == "yaml" else ""
        active.write_text(pattern.format(current_mode) if current_mode else empty, encoding="utf-8")
        template.write_text(pattern.format("shared-subscriptions"), encoding="utf-8")
        merge(template, active)
        assert (current_mode or "shared-subscriptions") in active.read_text(encoding="utf-8")


@pytest.fixture
def bash_executable():
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        bash = str(candidate) if candidate.is_file() else None
    else:
        bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required for offline launcher prompt tests.")
    return bash


def bootstrap_function(name):
    source = (ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    return re.search(r"^" + name + r"\(\) \{.*?^\}$", source, re.M | re.S)[0]


@pytest.mark.parametrize("mapping", [
    {"dev": "Dev", "stage": "Stage", "prod": "Prod"},
    {"dev": "Team: Dev/blue", "stage": "Stage", "prod": "Prod"},
])
def test_environment_shell_helpers_preserve_exact_names(bash_executable, mapping):
    source = (ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"
              "03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    helpers = "\n".join(re.search(r"^" + name + r"\(\) \{.*?^\}", source, re.M | re.S)[0]
                        for name in ("github_environment_name", "github_environment_url"))
    python = shlex.quote(Path(sys.executable).as_posix())
    script = (f"set -euo pipefail\nAIF_PYTHON=({python})\nenvironment_python=({python})\n"
              + bootstrap_function("aif_github_environment_name") + "\n" + helpers
              + '\nprintf "<%s>\\n" "$(aif_github_environment_name dev)" '
                '"$(github_environment_name dev)" "$(github_environment_url "$(github_environment_name dev)")"\n')
    result = subprocess.run([bash_executable, "-c", script], capture_output=True,
                            env=dict(os.environ, AIFACTORY_GITHUB_ENVIRONMENTS=json.dumps(mapping)), timeout=30)
    from urllib.parse import quote
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode() == f"<{mapping['dev']}>\n<{mapping['dev']}>\n<{quote(mapping['dev'], safe='')}>\n"


@pytest.mark.parametrize("purpose", ["AIFactoryBootstrap", ""])
@pytest.mark.parametrize("exists,expected_creates", [("true", 0), ("false", 1), ("error", 0), ("unknown", 0)])
def test_bootstrap_resource_group_is_create_if_absent(bash_executable, exists, expected_creates, purpose):
    script = """
set -euo pipefail
AIF_DRY_RUN=false
aif_error() { :; }
aif_mutate() { "$@"; }
az() {
  case "$1 $2" in
    "group exists") [[ "$AIF_TEST_EXISTS" != error ]] || return 9; printf '%s\\r\\n' "$AIF_TEST_EXISTS" ;;
    "group create") printf 'CREATE:%s\\n' "$*" ;;
    *) return 99 ;;
  esac
}
""" + bootstrap_function("aif_ensure_resource_group") + """
aif_ensure_resource_group subscription existing-rg location "$AIF_TEST_PURPOSE"
"""
    result = subprocess.run([bash_executable, "-c", script], capture_output=True, text=True,
                            env=dict(os.environ, AIF_TEST_EXISTS=exists, AIF_TEST_PURPOSE=purpose), timeout=30)
    assert result.stdout.count("CREATE") == expected_creates
    assert (result.returncode == 0) == (exists in ("true", "false"))
    assert ("--tags Purpose=" in result.stdout) == bool(expected_creates and purpose)


@pytest.mark.parametrize("name", ["aif_ensure_bootstrap_identity", "aif_ensure_seeding_keyvault",
                                 "aif_prepare_hub_dns", "aif_ensure_access_hub_vnet"])
def test_persistent_bootstrap_resource_groups_share_safe_absence_check(name):
    source = bootstrap_function(name)
    assert "aif_ensure_resource_group " in source
    assert "az group create" not in source


@pytest.mark.parametrize("existing", ["present", "absent", "error"])
def test_bootstrap_identity_only_creates_after_successful_absence_check(bash_executable, existing):
    script = """
set -euo pipefail
AIF_DRY_RUN=false AIF_IDENTITY_MODE=c AIF_DEPLOYMENT_IDENTITY_NAME=deployment-mi
AIF_DEV_SUBSCRIPTION_ID=dev AIF_STAGE_SUBSCRIPTION_ID=dev AIF_PROD_SUBSCRIPTION_ID=dev
AIF_BOOTSTRAP_RESOURCE_GROUP=bootstrap-rg AIF_LOCATION=swedencentral
AIF_TOPOLOGY=s AIF_ACCESS_HUB_MODE=integrated
aif_section() { :; }
aif_success() { :; }
aif_ensure_resource_group() { :; }
aif_ensure_role_assignment() { :; }
az() {
  case "$1 $2" in
    "identity list")
      case "$AIF_TEST_IDENTITY" in
        present) printf 'deployment-mi\\r\\n' ;;
        absent) : ;;
        error) return 9 ;;
      esac ;;
    "identity create") printf 'CREATE\\n' ;;
    "identity show") printf 'client-id\\nprincipal-id\\n' ;;
    *) return 99 ;;
  esac
}
""" + bootstrap_function("aif_ensure_bootstrap_identity") + "\naif_ensure_bootstrap_identity\n"
    result = subprocess.run([bash_executable, "-c", script], capture_output=True, text=True,
                            env=dict(os.environ, AIF_TEST_IDENTITY=existing), timeout=30)
    assert result.stdout.count("CREATE") == int(existing == "absent")
    assert (result.returncode == 0) == (existing != "error")


@pytest.mark.parametrize("failure", [False, True])
def test_separate_admin_group_preserves_team_and_propagates_failure(bash_executable, failure):
    script = """
set -euo pipefail
AIF_ADMIN_GROUP_MODE=separate AIF_ADMIN_GROUP_ID=admin-input
AIF_ADMIN_GROUP_NAME=admins AIF_ADMIN_MEMBER_EMAIL=admin@example.org
AIF_TEAM_GROUP_ID=team-id AIF_TEAM_GROUP_NAME=team AIF_TEAM_MEMBER_EMAIL=team@example.org
aif_ensure_team_group() {
  [[ "$AIF_TEAM_GROUP_ID/$AIF_TEAM_GROUP_NAME/$AIF_TEAM_MEMBER_EMAIL" == "admin-input/admins/admin@example.org" ]]
  [[ "$AIF_TEST_FAILURE" != true ]]
  AIF_TEAM_GROUP_ID=admin-result
}
""" + bootstrap_function("aif_ensure_admin_group") + """
aif_ensure_admin_group
printf '%s\\n' "$AIF_TEAM_GROUP_ID/$AIF_TEAM_GROUP_NAME/$AIF_TEAM_MEMBER_EMAIL/$AIF_ADMIN_GROUP_ID"
"""
    result = subprocess.run([bash_executable, "-c", script], capture_output=True, text=True,
                            env=dict(os.environ, AIF_TEST_FAILURE=str(failure).lower()), timeout=30)
    assert (result.returncode == 0) == (not failure)
    assert result.stdout == ("" if failure else "team-id/team/team@example.org/admin-result\n")


@pytest.mark.parametrize("mode", ["absent", "matching", "wrong-subject", "wrong-issuer", "wrong-audience", "error"])
def test_bootstrap_federation_never_overwrites_a_conflicting_binding(bash_executable, mode):
    python = shlex.quote(Path(sys.executable).as_posix())
    script = f"""
set -euo pipefail
AIF_PYTHON=(test_python)
AIF_DRY_RUN=false AIF_IDENTITY_MODE=c AIF_SCALESET_LIB_DIR=unused AIF_SCALESET_SUFFIX=001
AIF_IDENTITY_SUBSCRIPTION_ID=subscription AIF_IDENTITY_RESOURCE_GROUP=bootstrap-rg
AIF_IDENTITY_NAME=deployment-mi AIF_IDENTITY_CLIENT_ID=client-id GITHUB_REPOSITORY=example/factory
aif_section() {{ :; }}
test_python() {{
  if [[ "$1" == */github_environments.py ]]; then
    printf '%s' '{{"dev":"Dev: Blue","stage":"Stage","prod":"Prod"}}'
  else
    {python} "$@"
  fi
}}
gh() {{ printf 'GH:%s\\n' "$*"; }}
az() {{
  case "$1 $2 $3" in
    "identity federated-credential list")
      [[ "$AIF_TEST_FEDERATION" != error ]] || return 9
      local name=Prod
      case "$*" in
        *github-001-dev*) name="Dev%3A Blue" ;;
        *github-001-stage*) name=Stage ;;
      esac
      {python} -c '
import json, os, sys
mode = os.environ["AIF_TEST_FEDERATION"]
value = {{"subject": "repo:example/factory:environment:" + sys.argv[1],
          "issuer": "https://token.actions.githubusercontent.com",
          "audiences": ["api://AzureADTokenExchange"]}}
if mode.startswith("wrong-"):
    key = {{"wrong-subject": "subject", "wrong-issuer": "issuer", "wrong-audience": "audiences"}}[mode]
    value[key] = ["different"] if key == "audiences" else "different"
print(json.dumps([] if mode == "absent" else [value]))
' "$name" ;;
    "identity federated-credential create") printf 'CREATE:%s\\n' "$*" ;;
    *) return 99 ;;
  esac
}}
""" + bootstrap_function("aif_github_environment_name") + "\n" + bootstrap_function(
        "aif_configure_github_identity") + "\naif_configure_github_identity\n"
    result = subprocess.run([bash_executable, "-c", script], capture_output=True, text=True,
                            env=dict(os.environ, AIF_TEST_FEDERATION=mode), timeout=30)
    successful = mode in ("absent", "matching")
    assert (result.returncode == 0) == successful, result.stderr
    assert result.stdout.count("CREATE:") == (3 if mode == "absent" else 0)
    assert ("GH:secret set AZURE_CLIENT_ID --repo example/factory --env Dev: Blue " in result.stdout) == successful
    if mode == "absent":
        assert "--subject repo:example/factory:environment:Dev%3A Blue" in result.stdout
    assert "update" not in result.stdout and "delete" not in result.stdout


def run_sync_blocks(tmp_path, bash_executable, answer, *, use_json="y", update=None, uploader_exit=0):
    text = LAUNCHER.read_text(encoding="utf-8")
    function = text.split("confirm_update_github_variables() {", 1)[1].split(
        '\njson_override_choice="${AIFACTORY_USE_JSON_OVERRIDE:-}"', 1
    )[0]
    config_choice = text.split('\njson_override_choice=', 1)[1].split("\nfor command in git gh;", 1)[0]
    sync = text.split('aif_section "05 / Synchronize GitHub configuration"', 1)[1].split(
        '\nif [[ "$project_only" == "false" ]]; then', 1
    )[0]
    dispatch = text.split('\ngh workflow run "$WORKFLOW_FILE"', 1)[1].split('\nrun_id=""', 1)[0]
    config = tmp_path / "aifactory" / "variables.json"
    config.parent.mkdir()
    config.write_text('{"dev":{"projectPrefix":""}}', encoding="utf-8")
    (tmp_path / ".env").write_text('GITHUB_NEW_REPO="example/factory"\n', encoding="utf-8")
    # Execute only the prompt, upload decision, and dispatch blocks. All outbound
    # commands are functions; never source/run the update, git, or deployment steps.
    script = (
        'set -euo pipefail\n'
        'source "$AIF_TEST_LIBRARY"\n'
        'readonly CONFIG_FILE="aifactory/variables.json"\n'
        'readonly ENVIRONMENT="dev" WORKFLOW_FILE="infra-project.yml" RUNNER_LABEL="unit-runner"\n'
        'readonly project_only=false\n'
        'PYTHON=("$AIF_TEST_PYTHON")\n'
        'git() { printf "Unexpected git command in offline fixture\\n" >&2; return 99; }\n'
        'bash() { printf "BULK:%s\\n" "$*"; cat >/dev/null; return "$AIF_TEST_UPLOADER_EXIT"; }\n'
        'gh() { printf "GH:%s\\n" "$*"; if [[ "$1" == "secret" ]]; then cat >/dev/null; fi; }\n'
        'confirm_update_github_variables() {' + function +
        '\njson_override_choice=' + config_choice +
        '\n' + sync +
        '\ngh workflow run "$WORKFLOW_FILE"' + dispatch
    )
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"BASH_ENV", "ENV", "AIFACTORY_UPDATE_GITHUB_VARIABLES", "SHELLOPTS"}}
    environment.update({
        "AIF_TEST_LIBRARY": (ROOT / "bootstrap" / "ui" / "terminal.sh").as_posix(),
        "AIF_TEST_PYTHON": Path(sys.executable).as_posix(),
        "AIF_TEST_UPLOADER_EXIT": str(uploader_exit),
        "AIFACTORY_USE_JSON_OVERRIDE": use_json,
        "AIF_COLOR": "never",
    })
    if update is not None:
        environment["AIFACTORY_UPDATE_GITHUB_VARIABLES"] = update
    return subprocess.run(
        [bash_executable, "--noprofile", "--norc", "-c", script],
        input=answer, text=True, capture_output=True, cwd=tmp_path, env=environment,
        timeout=30, check=False,
    )


@pytest.mark.parametrize("answer", ["n\n", "N\n", "no\n", "\n", ""])
def test_json_override_no_skips_bulk_sync_but_keeps_json_transport_and_dispatch(tmp_path, bash_executable, answer):
    result = run_sync_blocks(tmp_path, bash_executable, answer)
    assert result.returncode == 0, result.stderr
    assert "Update GitHub variables and secrets from .env? [y/N]:" in result.stderr
    assert "Please enter" not in result.stderr
    assert "BULK:" not in result.stdout
    assert "Skipped bulk GitHub" in result.stdout
    assert result.stdout.count("GH:secret set AIFACTORY_CONFIG_JSON") == 1
    assert "--repo example/factory --env dev" in result.stdout
    assert "--raw-field config_file=aifactory/variables.json" in result.stdout


@pytest.mark.parametrize("answer", ["y\n", "Y\n", "yes\n", "YES\n"])
def test_json_override_yes_runs_existing_bulk_sync_once(tmp_path, bash_executable, answer):
    result = run_sync_blocks(tmp_path, bash_executable, answer)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("BULK:10-GH-create-or-update-github-variables.sh") == 1
    assert "GH:secret set AIFACTORY_CONFIG_JSON" in result.stdout
    assert "--raw-field config_file=aifactory/variables.json" in result.stdout


def test_invalid_prompt_answer_reprompts_and_can_decline(tmp_path, bash_executable):
    result = run_sync_blocks(tmp_path, bash_executable, "later\nN\n")
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("Update GitHub variables and secrets from .env? [y/N]:") == 2
    assert "Please enter" in result.stderr
    assert "BULK:" not in result.stdout


@pytest.mark.parametrize("update,expected_bulk", [("y", True), ("n", False)])
def test_explicit_unattended_choice_does_not_prompt(tmp_path, bash_executable, update, expected_bulk):
    result = run_sync_blocks(tmp_path, bash_executable, "", update=update)
    assert result.returncode == 0, result.stderr
    assert ("BULK:" in result.stdout) == expected_bulk
    assert "Update GitHub variables and secrets from .env? [y/N]:" not in result.stderr


def test_non_json_route_preserves_existing_sync_and_empty_override(tmp_path, bash_executable):
    result = run_sync_blocks(tmp_path, bash_executable, "", use_json="n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("BULK:10-GH-create-or-update-github-variables.sh") == 1
    assert "AIFACTORY_CONFIG_JSON" not in result.stdout
    assert "--raw-field config_file= --raw-field runner_selection=" in result.stdout
    assert "Update GitHub variables" not in result.stderr


def test_bulk_sync_failure_stops_before_secret_upload_or_dispatch(tmp_path, bash_executable):
    result = run_sync_blocks(tmp_path, bash_executable, "y\n", uploader_exit=7)
    assert result.returncode == 7
    assert "GH:" not in result.stdout


@pytest.mark.parametrize("path", [
    LAUNCHER,
    ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh",
    ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh",
])
def test_modified_launcher_has_valid_bash_syntax(bash_executable, path):
    result = subprocess.run(
        [bash_executable, "--noprofile", "--norc", "-n"],
        input=path.read_text(encoding="utf-8"), capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


WORKFLOWS = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"


def project_workflow(name="infra-project.yml"):
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def resolve_project_runner(tmp_path, bash_executable, payload, *, selection="from-config",
                           label="", legacy_label="", environment="dev"):
    step = next(step for step in project_workflow()["jobs"]["configure"]["steps"] if step.get("id") == "runner")
    config = tmp_path / "runner-config.json"
    if payload is not None:
        config.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "runner-output"
    output.unlink(missing_ok=True)
    env = os.environ | {
        "CONFIG_FILE": str(config) if payload is not None else "",
        "RUNNER_SELECTION": selection,
        "SELF_HOSTED_RUNNER_LABEL": label,
        "LEGACY_ADMIN_VM_RUNNER_LABEL": legacy_label,
        "TARGET_ENVIRONMENT": environment,
        "GITHUB_OUTPUT": str(output),
    }
    python = shlex.quote(sys.executable.replace("\\", "/"))
    result = subprocess.run(
        [bash_executable, "-c", f'python3() {{ {python} "$@"; }}\n' + step["run"]],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()) if output.exists() else {}
    return result, values


@pytest.mark.parametrize("selection,config,expected", [
    ("from-config", {}, "ubuntu-latest"),
    ("", {"useSelfHostedBuildAgent": "true"}, ["self-hosted", "Windows", "aifactory-admin-vm"]),
    ("from-config", {"useSelfHostedBuildAgent": True, "selfHostedRunnerOS": "linux"}, ["self-hosted", "Linux", "aifactory-admin-vm"]),
    ("self-hosted", {}, ["self-hosted", "Windows", "aifactory-admin-vm"]),
    ("self-hosted", {"selfHostedRunnerOS": "Linux"}, ["self-hosted", "Linux", "aifactory-admin-vm"]),
    ("self-hosted-windows", {"selfHostedRunnerOS": "Linux"}, ["self-hosted", "Windows", "aifactory-admin-vm"]),
    ("self-hosted-linux", {"selfHostedRunnerOS": "Windows"}, ["self-hosted", "Linux", "aifactory-admin-vm"]),
    ("github-hosted", {"useSelfHostedBuildAgent": True, "selfHostedRunnerOS": "Linux"}, "ubuntu-latest"),
])
def test_actual_project_runner_resolver_selection(tmp_path, bash_executable, selection, config, expected):
    result, output = resolve_project_runner(tmp_path, bash_executable, {"dev": config}, selection=selection)
    assert result.returncode == 0, result.stderr
    assert json.loads(output["runs_on"]) == expected
    assert output["use_self_hosted"] == str(isinstance(expected, list)).lower()


@pytest.mark.parametrize("selection,expected_os", [("self-hosted", "Windows"), ("self-hosted-linux", "Linux")])
def test_actual_runner_resolver_without_config_retains_legacy_label(
        tmp_path, bash_executable, selection, expected_os):
    result, output = resolve_project_runner(
        tmp_path, bash_executable, None, selection=selection, legacy_label="legacy-vm")
    assert result.returncode == 0, result.stderr
    assert json.loads(output["runs_on"]) == ["self-hosted", expected_os, "legacy-vm"]


@pytest.mark.parametrize("environment", ["stage", "prod"])
@pytest.mark.parametrize("override", [{}, {"selfHostedRunnerOS": "Windows", "selfHostedRunnerLabel": "stage-vm"}])
def test_actual_runner_resolver_uses_environment_config_and_dispatch_label(
        tmp_path, bash_executable, environment, override):
    payload = {"dev": {"useSelfHostedBuildAgent": True, "selfHostedRunnerOS": "Linux", "selfHostedRunnerLabel": "dev-vm"},
               "stage_prod": override}
    for label in ("", "explicit-vm"):
        result, output = resolve_project_runner(
            tmp_path, bash_executable, payload, environment=environment, label=label)
        assert result.returncode == 0, result.stderr
        assert json.loads(output["runs_on"]) == [
            "self-hosted", override.get("selfHostedRunnerOS", "Linux"),
            label or override.get("selfHostedRunnerLabel", "dev-vm"),
        ]


@pytest.mark.parametrize("runner_os", ["", "macOS", None, 42, ["Linux"]])
def test_actual_runner_resolver_rejects_invalid_config_os(tmp_path, bash_executable, runner_os):
    result, output = resolve_project_runner(
        tmp_path, bash_executable, {"dev": {"selfHostedRunnerOS": runner_os}}, selection="self-hosted")
    assert result.returncode != 0
    assert "selfHostedRunnerOS must be Windows or Linux" in result.stderr
    assert not output


@pytest.mark.parametrize("selection,label", [("unknown", ""), ("self-hosted-linux", "label\nruns_on=spoof")])
def test_actual_runner_resolver_rejects_invalid_selection_or_label(tmp_path, bash_executable, selection, label):
    result, output = resolve_project_runner(tmp_path, bash_executable, None, selection=selection, label=label)
    assert result.returncode != 0
    assert not output


@pytest.mark.parametrize("mode,os_type", [
    ("self-hosted", "Windows"), ("self-hosted", "Linux"), ("github-hosted", ""),
    ("self-hosted", ""), ("self-hosted", "unknown"),
])
def test_actual_bootstrap_dispatch_resolves_same_runner_os(tmp_path, bash_executable, mode, os_type):
    launcher = shlex.quote(str(ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh").replace("\\", "/"))
    script = f"""
source {launcher}
AIF_NO_WAIT=false; AIF_DRY_RUN=false; AIF_RUNNER_MODE={shlex.quote(mode)}; GHA_RUNNER_LABEL=fixture-vm
aif_simple_stage() {{ :; }}
aif_verify_common_resource_group() {{ :; }}
aif_ensure_private_network_access() {{ :; }}
aif_ensure_github_self_hosted_agent() {{ AIF_RUNNER_OS={shlex.quote(os_type)}; }}
aif_deploy_simple_application_gateway() {{ :; }}
aif_error() {{ echo "$*" >&2; }}
gh() {{ echo UNEXPECTED_CLOUD_CALL >&2; return 99; }}
az() {{ echo UNEXPECTED_CLOUD_CALL >&2; return 99; }}
aif_run_github_workflow() {{
  if [[ "$1" == infra-project.yml ]]; then shift 2; printf '%s\\n' "$@"; fi
}}
aif_deploy_github
"""
    result = subprocess.run(
        [bash_executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert "UNEXPECTED_CLOUD_CALL" not in result.stderr
    if mode == "self-hosted" and os_type not in {"Windows", "Linux"}:
        assert result.returncode != 0
        assert not result.stdout
        return
    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    fields = dict(args[index + 1].split("=", 1) for index in range(0, len(args), 2))
    assert fields["runner_selection"] in project_workflow()["on"]["workflow_dispatch"]["inputs"]["runner_selection"]["options"]
    result, output = resolve_project_runner(
        tmp_path, bash_executable, {"dev": {}}, selection=fields["runner_selection"],
        label=fields["self_hosted_runner_label"])
    assert result.returncode == 0, result.stderr
    assert json.loads(output["runs_on"]) == (
        ["self-hosted", os_type, "fixture-vm"] if mode == "self-hosted" else "ubuntu-latest")


def test_project_runner_os_transport_preserves_workflow_input_budget():
    workflow = project_workflow()
    assert len(workflow["on"]["workflow_dispatch"]["inputs"]) <= 10
    for job in ("deploy_infrastructure", "deploy_foundry"):
        assert workflow["jobs"][job]["with"]["runs_on"] == "${{ needs.configure.outputs.runs_on }}"
    phase = project_workflow("infra-project-phase.yml")
    assert phase["jobs"]["deploy-project"]["runs-on"] == "${{ fromJSON(inputs.runs_on) }}"


@pytest.mark.parametrize("expected_os,actual_os,missing_tool,success", [
    ("Windows", "Windows", "", True), ("Linux", "Linux", "", True),
    ("Windows", "Linux", "", False), ("Linux", "Windows", "", False),
    ("macOS", "macOS", "", False), ("Linux", "Linux", "python", False),
])
def test_actual_project_phase_validates_runner_os(tmp_path, expected_os, actual_os, missing_tool, success):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell is required for offline project phase tests")
    phase = project_workflow("infra-project-phase.yml")
    step = next(s for s in phase["jobs"]["deploy-project"]["steps"] if s.get("name") == "Validate self-hosted runner")
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "function Get-Command { param($Name) if ($Name -ne $env:MISSING_TOOL) { [pscustomobject]@{Name=$Name} } }\n"
        + step["run"]
    )
    env = os.environ | {"EXPECTED_RUNS_ON": json.dumps(["self-hosted", expected_os, "fixture-vm"]),
                        "ACTUAL_RUNNER_OS": actual_os, "MISSING_TOOL": missing_tool}
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", script], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    if not success:
        assert ("missing required commands: python" if missing_tool else "runner OS does not match") in result.stderr
