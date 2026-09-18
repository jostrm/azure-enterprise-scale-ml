"""Offline public promotion input and deployed-resource gates."""

import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("project_promotion", ROOT / "bootstrap/lib/project_deployment.py")
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUBS = dict(zip(("dev", "stage", "prod"), (f"{n}" * 8 + "-" + f"{n}" * 4 + "-" + f"{n}" * 4
                                         + "-" + f"{n}" * 4 + "-" + f"{n}" * 12 for n in (1, 2, 3))))


def document():
    values = {"project_number_000": "017", "tenantId": TENANT, "azureDevOpsTenantId": TENANT,
              "dev_sub_id": SUBS["dev"], "test_sub_id": SUBS["stage"], "prod_sub_id": SUBS["prod"],
              "admin_aifactoryPrefixRG": "mrvel-1-", "admin_aifactorySuffixRG": "-008",
              "admin_locationSuffix": "eus2", "admin_location": "eastus2",
              "projectPrefix": "esml-", "projectSuffix": "-rg", "GITHUB_NEW_REPO": "org/consumer"}
    return {"dev": values, "stage_prod": copy.deepcopy(values)}


@pytest.fixture(autouse=True)
def no_external_commands(monkeypatch):
    monkeypatch.setattr(pd.subprocess, "run", Mock(side_effect=AssertionError("No external CLI allowed")))
    monkeypatch.setattr(pd, "build_opener", Mock(side_effect=AssertionError("No network allowed")))


def resource(environment, data=None):
    values = (data or document())["dev" if environment == "dev" else "stage_prod"]
    selected = pd.project_environment.scope(values, environment, "017")
    name = selected["name"]
    return {"id": f"/subscriptions/{selected['subscription']}/resourceGroups/{name}", "name": name,
            "location": selected["location"], "properties": {"provisioningState": "Succeeded"}}


def deployment(target, present=(), route="gha", data=None):
    value = object.__new__(pd.Deployment)
    value.route = route
    value.environment = {}
    value.selected = pd.validate_config(data or document(), "017", target)
    value.config = pd.canonical_json(data or document())
    value.command = Mock(side_effect=AssertionError("No mutation allowed"))
    inventory = {SUBS[env]: [resource(env, data)] if env in present else [] for env in SUBS}

    def read(argv):
        assert argv[0] == "az" and argv[-2:] == ["--output", "json"]
        subscription = argv[argv.index("--subscription") + 1]
        if argv[1:3] == ["account", "show"]:
            return {"id": subscription, "tenantId": TENANT, "state": "Enabled", "user": {"name": "offline-test"}}
        assert argv[1:3] == ["group", "list"]
        return inventory[subscription]

    value.read_json = Mock(side_effect=read)
    return value, inventory


@pytest.mark.parametrize("route", ["gha", "ado"])
@pytest.mark.parametrize("target,present,allowed", [
    ("dev", (), True),
    ("stage", (), False), ("stage", ("dev",), True), ("stage", ("stage",), False),
    ("prod", (), False), ("prod", ("dev",), True), ("prod", ("stage",), True),
    ("prod", ("dev", "stage"), True), ("prod", ("prod",), False),
])
def test_predecessor_truth_table(route, target, present, allowed):
    value, _ = deployment(target, present, route)
    if allowed:
        value.verify_predecessor()
    else:
        with pytest.raises(ValueError, match="requires an existing"):
            value.verify_predecessor()
    value.command.assert_not_called()
    if target == "dev":
        value.read_json.assert_not_called()
    else:
        assert all("--subscription" in call.args[0] for call in value.read_json.call_args_list)


@pytest.mark.parametrize("field,replacement", [
    ("name", "mrvel-1-esml-project018-eus2-dev-008-rg"),
    ("id", "/subscriptions/" + SUBS["prod"] + "/resourceGroups/mrvel-1-esml-project017-eus2-dev-008-rg"),
    ("name", "mrvel-1-esml-project017-eus2-dev-009-rg"),
    ("name", "other-esml-project017-eus2-dev-008-rg"),
    ("name", "mrvel-1-esml-project017-weu-dev-008-rg"),
    ("name", "mrvel-1-esml-project017-eus2-stage-008-rg"),
])
def test_other_factory_project_region_subscription_never_qualifies(field, replacement):
    value, inventory = deployment("stage", ("dev",))
    inventory[SUBS["dev"]][0][field] = replacement
    with pytest.raises(ValueError, match="requires an existing"):
        value.verify_predecessor()


@pytest.mark.parametrize("state", ["Deleting", "Failed", "Canceled", "Creating", ""])
def test_not_deployed_states_do_not_count(state):
    value, inventory = deployment("stage", ("dev",))
    inventory[SUBS["dev"]][0]["properties"]["provisioningState"] = state
    with pytest.raises(ValueError, match="requires an existing"):
        value.verify_predecessor()


def test_resource_group_alone_counts_when_state_is_not_returned():
    value, inventory = deployment("stage", ("dev",))
    del inventory[SUBS["dev"]][0]["properties"]
    value.verify_predecessor()
    assert len(value.read_json.call_args_list) == 2


@pytest.mark.parametrize("groups", [None, {}, "[]", [{}], [False], [{"name": "rg"}]])
def test_malformed_inventory_is_not_absence(groups):
    value, inventory = deployment("prod", ("stage",))
    inventory[SUBS["dev"]] = groups
    with pytest.raises(ValueError, match="Invalid Azure resource-group inventory"):
        value.verify_predecessor()
    assert not any(SUBS["stage"] in call.args[0] and call.args[0][1] == "group"
                   for call in value.read_json.call_args_list)


def test_wrong_predecessor_tenant_blocks_without_querying_groups():
    value, _ = deployment("stage", ("dev",))
    value.read_json = Mock(return_value={"id": SUBS["dev"], "tenantId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"})
    with pytest.raises(ValueError, match="metadata"):
        value.verify_predecessor()
    assert value.read_json.call_count == 1


def test_azure_cli_failure_is_not_treated_as_missing_dev():
    value, _ = deployment("prod", ("stage",))
    value.read_json = Mock(side_effect=ValueError("az group failed (exit 1)"))
    with pytest.raises(ValueError, match="failed"):
        value.verify_predecessor()
    value.read_json.assert_called_once()


def test_custom_naming_and_stage_physical_test_alias():
    data = document()
    data["stage_prod"].update(projectPrefix="team-", projectSuffix="-workload",
                              admin_locationSuffix="weu", admin_aifactoryPrefixRG="factory-custom-")
    value, inventory = deployment("prod", ("stage",), data=data)
    assert inventory[SUBS["stage"]][0]["name"] == "factory-custom-team-project017-weu-test-008-workload"
    value.verify_predecessor()
    inventory[SUBS["stage"]][0]["name"] = inventory[SUBS["stage"]][0]["name"].replace("-test-", "-stage-")
    with pytest.raises(ValueError, match="requires an existing"):
        value.verify_predecessor()


@pytest.mark.parametrize("field,invalid", [
    (field, invalid)
    for field in ("admin_locationSuffix", "admin_aifactoryPrefixRG", "admin_aifactorySuffixRG")
    for invalid in (None, "", "$(unresolved)", "prefix;command", "bad/name")
    if invalid != "" or field == "admin_locationSuffix"
])
def test_missing_or_nonliteral_factory_identity_blocks(field, invalid):
    data = document()
    data["dev"][field] = invalid
    value, _ = deployment("stage")
    value.config = pd.canonical_json(data)
    with pytest.raises(ValueError, match="resource-group naming"):
        value.verify_predecessor()
    assert all(call.args[0][1:3] == ["account", "show"] for call in value.read_json.call_args_list)


def test_mcp_scope_keeps_existing_behavior():
    value, _ = deployment("stage", route="ado")
    value.environment["AIFACTORY_PROJECT_DEPLOYMENT_SCOPE"] = "azure-mcp"
    value.verify_predecessor()
    value.read_json.assert_not_called()


def test_empty_explicit_prefixes_and_bicep_project_defaults():
    values = document()["dev"]
    values.update(admin_aifactoryPrefixRG="", admin_aifactorySuffixRG="", projectPrefix="", projectSuffix="")
    assert pd.project_environment.scope(values, "dev", "017")["name"] == "project017-eus2-dev"
    del values["projectPrefix"], values["projectSuffix"]
    assert pd.project_environment.scope(values, "dev", "017")["name"] == "esml-project017-eus2-dev-rg"


@pytest.mark.parametrize("number", [17, "17"])
def test_rg_name_preserves_the_raw_project_number_passed_to_bicep(number):
    values = document()["dev"]
    values["project_number_000"] = number
    assert pd.project_environment.scope(values, "dev", "017")["name"] == "mrvel-1-esml-project17-eus2-dev-008-rg"


@pytest.mark.parametrize("state", [None, 123, {}])
def test_invalid_explicit_state_cannot_prove_deployment(state):
    value, inventory = deployment("stage", ("dev",))
    inventory[SUBS["dev"]][0]["properties"]["provisioningState"] = state
    with pytest.raises(ValueError, match="provisioning state"):
        value.verify_predecessor()


@pytest.mark.parametrize("target", ["stage", "prod"])
@pytest.mark.parametrize("number", [17, "17", "017"])
def test_public_flag_discovers_project_from_existing_json(tmp_path, target, number):
    (tmp_path / "aifactory").mkdir()
    data = document()
    for section in data.values():
        section["project_number_000"] = number
    config = tmp_path / "aifactory/variables.json"
    config.write_text(json.dumps(data), encoding="utf-8")
    inputs = pd.deployment_inputs({"AIFACTORY_REPO_ROOT": str(tmp_path)}, target)
    assert inputs == ("017", target, str(config), str(tmp_path))


def test_public_flag_respects_explicit_config_and_project(tmp_path):
    (tmp_path / "aifactory").mkdir()
    config = tmp_path / "aifactory/selected.json"
    config.write_text(json.dumps(document()), encoding="utf-8")
    env = {"AIFACTORY_REPO_ROOT": str(tmp_path), "AIFACTORY_PROJECT_CONFIG": str(config),
           "AIFACTORY_PROJECT_NUMBER": "017", "AIFACTORY_TARGET_ENVIRONMENT": "prod"}
    assert pd.deployment_inputs(env, "prod")[:3] == ("017", "prod", str(config))
    env["AIFACTORY_PROJECT_NUMBER"] = "018"
    with pytest.raises(ValueError, match="identity does not match"):
        pd.deployment_inputs(env, "prod")
    with pytest.raises(ValueError, match="conflicts"):
        pd.deployment_inputs(env, "stage")


@pytest.mark.parametrize("missing", ["AIFACTORY_PROJECT_NUMBER", "AIFACTORY_PROJECT_CONFIG",
                                   "AIFACTORY_TARGET_ENVIRONMENT", "AIFACTORY_REPO_ROOT"])
def test_env_only_api_still_requires_all_reviewed_inputs(missing):
    env = dict(zip(("AIFACTORY_PROJECT_NUMBER", "AIFACTORY_TARGET_ENVIRONMENT",
                    "AIFACTORY_PROJECT_CONFIG", "AIFACTORY_REPO_ROOT"),
                   ("017", "stage", "selected.json", "consumer")))
    del env[missing]
    with pytest.raises(ValueError, match="All reviewed"):
        pd.deployment_inputs(env)


@pytest.mark.parametrize("raw", ["{", "[]", "null", '{"dev":[]}', '{"dev":{"project_number_000":"000"}}'])
def test_public_invalid_json_cannot_reach_commands(tmp_path, raw):
    (tmp_path / "aifactory").mkdir()
    (tmp_path / "aifactory/variables.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        pd.deployment_inputs({"AIFACTORY_REPO_ROOT": str(tmp_path)}, "prod")


def test_public_missing_json_and_outside_factory_are_rejected(tmp_path):
    (tmp_path / "aifactory").mkdir()
    env = {"AIFACTORY_REPO_ROOT": str(tmp_path)}
    with pytest.raises(ValueError, match="bounded file"):
        pd.deployment_inputs(env, "stage")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(document()), encoding="utf-8")
    env["AIFACTORY_PROJECT_CONFIG"] = str(outside)
    with pytest.raises(ValueError, match="inside this factory"):
        pd.deployment_inputs(env, "stage")


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_predecessor_disappearing_after_review_blocks_dispatch(tmp_path, route):
    value, inventory = deployment("stage", ("dev",), route)
    value.verify_predecessor()
    inventory[SUBS["dev"]].clear()
    value.repository = "org/consumer" if route == "gha" else "consumer"
    if route == "gha":
        value.command = Mock(side_effect=["a" * 40, "a" * 40 + "\trefs/heads/main"])
        with pytest.raises(ValueError, match="requires an existing"):
            value.github()
        assert all(call.args[0][0] == "git" for call in value.command.call_args_list)
    else:
        value.ado = Mock(return_value={"value": [{"id": 7, "repository": {"name": "consumer"},
                                                "process": {"yamlFilename": pd.ADO_PIPELINE}}]})
        with pytest.raises(ValueError, match="requires an existing"):
            value.azure_devops()
        assert all(call.args[0] == "GET" for call in value.ado.call_args_list)


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_prepare_checks_deployed_predecessor_before_update(tmp_path, route):
    value, _ = deployment("stage", route=route)
    value.root = tmp_path
    (tmp_path / ".git").mkdir()
    (tmp_path / "aifactory").mkdir()
    config = tmp_path / "aifactory/variables.json"
    config.write_text(json.dumps(document()), encoding="utf-8")
    for relative in value.files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pd.CONTRACT, encoding="utf-8")
    origin = "https://github.com/org/consumer" if route == "gha" else "https://dev.azure.com/org/project/_git/consumer"
    value.command = Mock(side_effect=lambda argv, **kw: origin if argv[0] == "git" else 0)
    azure_read = value.read_json
    value.read_json = Mock(side_effect=lambda argv: {"id": 17} if argv[:2] == ["gh", "api"] else azure_read(argv))
    value.verify_ado_repository = Mock()
    value.update = Mock()
    with pytest.raises(ValueError, match="requires an existing"):
        value.prepare("017", "stage", config)
    value.update.assert_not_called()
    assert all(call.args[0][:3] in (["git", "remote", "get-url"], ["gh", "auth", "status"])
               for call in value.command.call_args_list)


@pytest.mark.parametrize("route", ["gha", "ado"])
@pytest.mark.parametrize("target,predecessor", [("stage", "dev"), ("prod", "dev"), ("prod", "stage")])
@pytest.mark.parametrize("present_before_update", [False, True])
def test_public_main_blocks_missing_or_disappearing_source(tmp_path, monkeypatch, route, target, predecessor,
                                                         present_before_update):
    value, inventory = deployment(target, (predecessor,) if present_before_update else (), route)
    value.root = tmp_path
    (tmp_path / ".git").mkdir()
    (tmp_path / "aifactory").mkdir()
    config = tmp_path / "aifactory/variables.json"
    config.write_text(json.dumps(document()), encoding="utf-8")
    for relative in value.files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pd.CONTRACT, encoding="utf-8")
    origin = "https://github.com/org/consumer" if route == "gha" else "https://dev.azure.com/org/project/_git/consumer"
    def command(argv, **kwargs):
        if argv[:3] == ["git", "remote", "get-url"]:
            return origin
        if argv[:2] == ["git", "rev-parse"]:
            return "a" * 40
        if argv[:2] == ["git", "ls-remote"]:
            return "a" * 40 + "\trefs/heads/main"
        assert argv == ["gh", "auth", "status"]
        return 0
    value.command = Mock(side_effect=command)
    reader = value.read_json
    value.read_json = Mock(side_effect=lambda argv: {"id": 17} if argv[:2] == ["gh", "api"] else reader(argv))
    value.verify_ado_repository = Mock()
    value.ado = Mock(return_value={"value": [{"id": 7, "repository": {"name": "consumer"},
                                            "process": {"yamlFilename": pd.ADO_PIPELINE}}]})
    value.update = Mock(side_effect=lambda _: inventory[SUBS[predecessor]].clear())
    monkeypatch.setattr(pd, "Deployment", lambda *args: value)
    for key in list(pd.os.environ):
        if key.startswith(("AIFACTORY_", "ADO_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("AIFACTORY_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("AIFACTORY_PROJECT_ONLY", "true")
    monkeypatch.setattr(pd.sys, "argv", ["project_deployment.py", "--route", route, "--state-dir", str(tmp_path),
                                       "--aifactory-env", target])
    assert pd.main() == 1
    assert value.update.call_count == int(present_before_update)
    assert all(call.args[0] == "GET" for call in value.ado.call_args_list)
    assert not any(call.args[0][:2] == ["gh", "secret"] for call in value.command.call_args_list)


@pytest.mark.parametrize("route", ["gha", "ado"])
def test_actual_project_only_update_reads_installed_version_without_mutation(tmp_path, monkeypatch, route):
    value, _ = deployment("prod", ("stage",), route)
    value.root = tmp_path
    value.environment = {"AIFACTORY_VERSION": "125", "AIF_SUBMODULE_REF": "b" * 40}
    pd.release_version.save(tmp_path, {**pd.release_version.select("125", environ={}), "resolved_ref": "b" * 40})
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    value.command = Mock(return_value="b" * 40)
    value.update(True)
    value.command.assert_called_once_with(["git", "-C", "azure-enterprise-scale-ml", "rev-parse", "HEAD"], capture=True)
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize("project", ["000", "1000", "-17", "17x", None, True, 17.0])
def test_invalid_inferred_project_is_rejected(tmp_path, project):
    (tmp_path / "aifactory").mkdir()
    data = document()
    data["dev"]["project_number_000"] = project
    (tmp_path / "aifactory/variables.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        pd.deployment_inputs({"AIFACTORY_REPO_ROOT": str(tmp_path)}, "stage")


@pytest.mark.parametrize("name", ["AIFACTORY_PROJECT_NUMBER", "AIFACTORY_PROJECT_CONFIG"])
def test_empty_explicit_reviewed_input_is_not_replaced_by_inference(tmp_path, name):
    with pytest.raises(ValueError, match="must not be empty"):
        pd.deployment_inputs({"AIFACTORY_REPO_ROOT": str(tmp_path), name: ""}, "prod")


def test_case_insensitive_rg_identity_and_duplicate_response(tmp_path):
    value, inventory = deployment("stage", ("dev",))
    row = inventory[SUBS["dev"]][0]
    row["id"], row["name"] = row["id"].upper(), row["name"].upper()
    value.verify_predecessor()
    inventory[SUBS["dev"]].append(copy.deepcopy(row))
    with pytest.raises(ValueError, match="Ambiguous"):
        value.verify_predecessor()


def test_predecessor_naming_matches_foundation_and_both_pipeline_mappings():
    foundation = (ROOT / "environment_setup/aifactory/bicep/esml-genai-1/01-foundation.bicep").read_text(encoding="utf-8")
    assert "param projectPrefix string = 'esml-'" in foundation
    assert "param projectSuffix string = '-rg'" in foundation
    assert "var projectName = 'prj${projectNumber}'" in foundation
    assert "${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}" in foundation
    gha = (ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
    assert "inputs.environment == 'stage' && 'test'" in gha
    for name, key in (("commonRGNamePrefix", "admin_aifactoryPrefixRG"), ("aifactorySuffixRG", "admin_aifactorySuffixRG"),
                      ("locationSuffix", "admin_locationSuffix"), ("projectPrefix", "projectPrefix"),
                      ("projectSuffix", "projectSuffix")):
        assert f'--parameters {name}="${{{{ env.{key} }}}}"' in gha
    ado = (ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-genai.yaml").read_text(encoding="utf-8")
    assert 'dev_test_prod: "test"' in ado
