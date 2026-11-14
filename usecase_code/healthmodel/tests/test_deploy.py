from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aifactory_healthmodel import deploy
from aifactory_healthmodel.application.ports import CallableClientFactory, ClientFactory

SUB = "00000000-0000-0000-0000-0000000000aa"
TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT_RG = "spider-esml-project001-sdc-dev-001-rg"
COMMON_RG = "spider-esml-common-sdc-dev-001"
WRITE_VERBS = {("deployment", "group", "create"), ("provider", "register")}


class FakeAz:
    """Records az invocations and answers from canned data."""

    def __init__(self, resources, *, registered=True, account=None, fail=None, models=()):
        self.resources = resources
        self.registered = registered
        self.account = account or {"id": SUB, "tenantId": TENANT}
        self.fail = fail or {}
        self.models = list(models)
        self.calls = []
        self.bodies = []
        self.deployed_parameters = []

    def __call__(self, args, input_text=None):
        args = list(args)
        self.calls.append(args)
        key = tuple(args[:3])
        for prefix, error in self.fail.items():
            if tuple(args[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(args, 1, "", error)
        if args[:2] == ["account", "show"]:
            return self.ok(self.account)
        if args[:1] == ["rest"]:
            url = args[args.index("--url") + 1]
            method = args[args.index("--method") + 1]
            body = None
            if "--body" in args:
                body = json.loads(Path(args[args.index("--body") + 1][1:]).read_text(encoding="utf-8"))
                self.bodies.append(body)
            if "Microsoft.ResourceGraph/resources" in url:
                query = body["query"]
                rows = [r for r in self.resources + self.models
                        if r["resourceGroup"].lower() in query.lower() or (
                            r["type"] == "microsoft.cloudhealth/healthmodels" and "cloudhealth" in query)]
                return self.ok({"data": rows, "count": len(rows)})
            if url.split("?")[0].endswith("/providers/Microsoft.CloudHealth") and method == "get":
                return self.ok({"registrationState": "Registered" if self.registered else "NotRegistered",
                                "resourceTypes": [{"resourceType": "healthmodels",
                                                   "locations": ["Sweden Central", "Central US", "West Europe"]}]})
            if "/entities" in url or "/relationships" in url:
                return self.ok({"value": []})
            return self.ok({})
        if key == ("deployment", "group", "create"):
            params = Path(args[args.index("--parameters") + 1][1:])
            self.deployed_parameters.append(json.loads(params.read_text(encoding="utf-8")))
            return self.ok({"properties": {"provisioningState": "Succeeded", "outputs": {
                "healthModelId": {"value": f"/subscriptions/{SUB}/resourceGroups/{args[args.index('--resource-group') + 1]}"
                                           "/providers/Microsoft.CloudHealth/healthmodels/x"}}}})
        if key == ("deployment", "group", "what-if"):
            return self.ok({"changes": [{"changeType": "Create", "resourceId": "/x/entities/a"},
                                        {"changeType": "NoChange", "resourceId": "/x/entities/b"}]})
        if args[:2] == ["provider", "register"]:
            self.registered = True
            return self.ok({})
        raise AssertionError(f"Unexpected az call: {args}")

    @staticmethod
    def ok(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    def writes(self):
        return [c for c in self.calls if tuple(c[:3]) in WRITE_VERBS or tuple(c[:2]) in WRITE_VERBS
                or (c[:1] == ["rest"] and c[c.index("--method") + 1] in ("put", "delete")
                    and "ResourceGraph" not in c[c.index("--url") + 1])]


def variables(tmp_path, **dev):
    document = {"dev": {
        "tenantId": TENANT, "dev_sub_id": SUB, "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "admin_aifactoryPrefixRG": "spider-", "admin_aifactorySuffixRG": "-001", "projectPrefix": "esml-",
        "projectSuffix": "-rg", "vnetResourceGroupBase": "esml-common", "project_number_000": "001",
        "enableAISearch": "true", "enableAIFoundry": "true", **dev,
    }, "stage_prod": {}}
    path = tmp_path / "aifactory" / "variables.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def cli(tmp_path, *extra):
    return ["--consumer-root", str(tmp_path), "--variables-json", "aifactory/variables.json",
            "--environment", "dev", "--project", "001", *extra]


def test_plan_is_read_only_and_reports_the_model(tmp_path, test_env_resources, capsys):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path)]), az=fake)
    assert fake.writes() == []
    project = result["models"][0]
    assert project["model"] == "hm-spider-prj001-sdc-dev-001"
    assert project["location"] == "swedencentral" and project["azureWritesPerformed"] is False
    assert project["profiles"]["foundry"] == 1
    assert "PLAN ONLY" in capsys.readouterr().out


def test_plan_fails_closed_when_signed_in_account_differs(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources, account={"id": "99999999-9999-9999-9999-999999999999", "tenantId": TENANT})
    with pytest.raises(RuntimeError, match="does not match"):
        deploy.run(deploy.parse_args(["plan", *cli(tmp_path)]), az=fake)
    assert fake.writes() == []


def test_discovery_query_is_scoped_to_the_factory_resource_groups(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    deploy.run(deploy.parse_args(["plan", *cli(tmp_path)]), az=fake)
    query = next(b for b in fake.bodies if "query" in b)
    assert query["subscriptions"] == [SUB]
    assert PROJECT_RG in query["query"] and COMMON_RG in query["query"]


def test_deploy_requires_registered_provider_unless_explicitly_allowed(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources, registered=False)
    with pytest.raises(RuntimeError, match="--register-provider"):
        deploy.run(deploy.parse_args(["deploy", *cli(tmp_path)]), az=fake)
    assert fake.writes() == []
    fake = FakeAz(test_env_resources, registered=False)
    deploy.run(deploy.parse_args(["deploy", *cli(tmp_path), "--register-provider"]), az=fake, sleep=lambda s: None)
    assert ["provider", "register", "--namespace", "Microsoft.CloudHealth", "--subscription", SUB,
            "--only-show-errors"] in fake.calls


def test_deploy_writes_one_incremental_deployment_per_model(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["deploy", *cli(tmp_path), "--scope", "all",
                                           "--alert-email", "ops@contoso.com", "--health-objective", "98"]), az=fake)
    creates = [c for c in fake.calls if c[:3] == ["deployment", "group", "create"]]
    assert [c[c.index("--resource-group") + 1] for c in creates] == [PROJECT_RG, COMMON_RG]
    for command in creates:
        assert command[command.index("--mode") + 1] == "Incremental"
        assert Path(command[command.index("--template-file") + 1]).name == "main.bicep"
        assert command[command.index("--subscription") + 1] == SUB
    project_params = fake.deployed_parameters[0]["parameters"]
    assert project_params["actionGroupEmails"]["value"] == ["ops@contoso.com"]
    assert project_params["createActionGroup"]["value"] is True
    assert project_params["healthObjective"]["value"] == 98
    assert [m["azureWritesPerformed"] for m in result["models"]] == [True, True]
    assert not list(tmp_path.glob(".healthmodel-*")), "work directory is removed"


def test_common_model_nests_project_models_deployed_in_the_same_run(tmp_path, test_env_resources):
    variables(tmp_path)
    project_model = {"id": f"/subscriptions/{SUB}/resourceGroups/{PROJECT_RG}/providers/Microsoft.CloudHealth/healthmodels/"
                           "hm-spider-prj001-sdc-dev-001", "name": "hm-spider-prj001-sdc-dev-001",
                     "type": "microsoft.cloudhealth/healthmodels", "kind": "", "resourceGroup": PROJECT_RG, "tags": {}}
    fake = FakeAz(test_env_resources, models=[project_model])
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--scope", "common"]), az=fake)
    assert result["models"][0]["profiles"].get("health-model") == 1


def test_unsupported_region_without_fallback_fails_before_writes(tmp_path, test_env_resources):
    variables(tmp_path, admin_location="uaenorth")
    fake = FakeAz(test_env_resources)
    with pytest.raises(ValueError, match="--health-model-location"):
        deploy.run(deploy.parse_args(["deploy", *cli(tmp_path)]), az=fake)
    assert fake.writes() == []
    deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--health-model-location", "westeurope"]), az=fake)


def test_what_if_is_summarised(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--what-if"]), az=fake)
    assert result["models"][0]["whatIf"] == {"Create": 1, "NoChange": 1}
    assert fake.writes() == []


def test_overrides_and_alert_policy_files_are_validated(tmp_path, test_env_resources):
    variables(tmp_path)
    (tmp_path / "overrides.json").write_text(json.dumps({"profiles": {"databricks": {"enabled": False}}}))
    (tmp_path / "policy.json").write_text(json.dumps({"rootDegradedSeverity": ""}))
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--overrides", str(tmp_path / "overrides.json"),
                                           "--alert-policy", str(tmp_path / "policy.json")]), az=fake)
    assert "databricks" not in result["models"][0]["profiles"]
    (tmp_path / "policy.json").write_text(json.dumps({"rootDegradedSeverity": "Sev7"}))
    with pytest.raises(ValueError, match="severity"):
        deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--alert-policy", str(tmp_path / "policy.json")]), az=fake)


def test_prune_deletes_only_stale_managed_objects(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    deleted = []

    class Client:
        def __init__(self, model_id, transport):
            pass

        def stale_managed(self, desired_entities, desired_relationships):
            assert "layer-genai" in desired_entities
            return {"entities": ["foundry-old-abc123"], "relationships": ["layer-genai-to-foundry-old-abc123"]}

        def delete_relationship(self, name):
            deleted.append(("relationship", name))

        def delete_entity(self, name):
            deleted.append(("entity", name))

        def add_annotation(self, entity, details, description=None):
            deleted.append(("annotation", entity, details["event"]))

    def use_fake_client(services):
        services.replace(ClientFactory, instance=CallableClientFactory(Client))

    result = deploy.run(deploy.parse_args(["deploy", *cli(tmp_path), "--prune"]), az=fake, configure=use_fake_client)
    assert deleted == [("relationship", "layer-genai-to-foundry-old-abc123"), ("entity", "foundry-old-abc123"),
                       ("annotation", "root", "aifactory-healthmodel-deployment")]
    assert result["models"][0]["pruned"] == {"entities": ["foundry-old-abc123"],
                                             "relationships": ["layer-genai-to-foundry-old-abc123"]}


def test_log_signals_use_the_discovered_factory_workspace(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--log-signals"]), az=fake)
    model = result["models"][0]
    assert model["profiles"]["databricks"] == 1
    assert "microsoft.databricks/workspaces" not in model["notMonitorable"]
    assert model["logAnalyticsWorkspace"].endswith("/workspaces/la-cmn-sdc-dev-bltsc-001")
    default = deploy.run(deploy.parse_args(["plan", *cli(tmp_path)]), az=fake)["models"][0]
    assert "databricks" not in default["profiles"] and default["logAnalyticsWorkspace"] is None


def test_log_signals_require_exactly_one_workspace(tmp_path, test_env_resources):
    variables(tmp_path)
    rows = [r for r in test_env_resources if r["type"] != "microsoft.operationalinsights/workspaces"]
    with pytest.raises(ValueError, match="--log-analytics-workspace-id"):
        deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--log-signals"]), az=FakeAz(rows))


def test_explain_ships_the_alert_defaults_in_the_report(tmp_path, test_env_resources):
    variables(tmp_path)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path)]), az=FakeAz(test_env_resources))
    assert result["models"][0]["alertPolicy"]["rootUnhealthySeverity"] == "Sev1"


def test_explicit_scope_works_without_variables_json(test_env_resources):
    fake = FakeAz(test_env_resources)
    args = deploy.parse_args([
        "plan", "--tenant-id", TENANT, "--subscription", SUB, "--environment", "dev", "--project", "001",
        "--location", "swedencentral", "--location-suffix", "sdc", "--project-resource-group", PROJECT_RG,
        "--common-resource-group", COMMON_RG, "--resource-group-prefix", "spider-", "--resource-group-suffix", "-001",
    ])
    result = deploy.run(args, az=fake)
    assert result["models"][0]["model"] == "hm-spider-prj001-sdc-dev-001"


def test_variables_json_must_stay_inside_the_consumer_root(tmp_path, test_env_resources):
    variables(tmp_path)
    args = deploy.parse_args(["plan", "--consumer-root", str(tmp_path), "--variables-json", "../outside.json",
                              "--environment", "dev", "--project", "001"])
    with pytest.raises(ValueError, match="inside"):
        deploy.run(args, az=FakeAz(test_env_resources))


def test_main_returns_nonzero_without_leaking_raw_errors(tmp_path, test_env_resources, capsys, monkeypatch):
    variables(tmp_path)
    fake = FakeAz(test_env_resources, fail={("account", "show"): "ERROR: token=abc.def secret stuff"})
    monkeypatch.setattr(deploy, "_default_az", lambda: fake)
    assert deploy.main(["plan", *cli(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "ERROR:" in err and "abc.def" not in err


# ---------------------------------------------------------------- several model definitions
def test_extra_models_join_the_built_in_scope(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--scope", "all", "--model", "agents"]), az=fake)
    assert [m["definition"] for m in result["models"]] == ["project", "agents", "common"]
    assert [m["model"] for m in result["models"]] == [
        "hm-spider-prj001-sdc-dev-001", "hm-spider-agt001-sdc-dev-001", "hm-spider-cmn-sdc-dev-001"]
    queries = [b for b in fake.bodies if "query" in b]
    assert len(queries) == 1, "one Resource Graph discovery serves every model of the run"


def test_model_without_scope_plans_only_that_model(tmp_path, test_env_resources):
    variables(tmp_path)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--model", "agents"]), az=FakeAz(test_env_resources))
    assert [m["definition"] for m in result["models"]] == ["agents"]


def test_consumer_definitions_from_a_folder_and_a_file(tmp_path, test_env_resources):
    variables(tmp_path)
    folder = tmp_path / "healthmodels"
    folder.mkdir()
    definition = {"key": "lake", "nameToken": "lake", "home": "common", "rootDisplayName": "Data lake ({env})",
                  "layers": [{"fromCatalog": True, "select": {"profile": "adls-gen2"}}]}
    (folder / "lake.json").write_text(json.dumps(definition), encoding="utf-8")
    other = {**definition, "key": "vault", "nameToken": "kv{project}",
             "layers": [{"fromCatalog": True, "select": {"profile": "keyvault", "origin": "project"}}]}
    (tmp_path / "vault.json").write_text(json.dumps(other), encoding="utf-8")
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["deploy", *cli(tmp_path), "--definitions-dir", str(folder),
                                           "--model", "lake", "--model", str(tmp_path / "vault.json"),
                                           "--no-annotate"]), az=fake)
    assert [(m["model"], m["profiles"]) for m in result["models"]] == [
        ("hm-spider-lake-sdc-dev-001", {"adls-gen2": 2}), ("hm-spider-kv001-sdc-dev-001", {"keyvault": 1})]
    assert [p["parameters"]["healthModelName"]["value"] for p in fake.deployed_parameters] == [
        "hm-spider-lake-sdc-dev-001", "hm-spider-kv001-sdc-dev-001"]


def test_unknown_model_definition_fails_before_azure_calls(tmp_path, test_env_resources):
    variables(tmp_path)
    fake = FakeAz(test_env_resources)
    with pytest.raises(ValueError, match="Unknown model definition 'nope'"):
        deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--model", "nope"]), az=fake)
    assert fake.calls == []


def test_offline_inventory_plan_needs_no_azure(tmp_path, test_env_resources):
    variables(tmp_path)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"data": test_env_resources}), encoding="utf-8")
    fake = FakeAz(test_env_resources)
    result = deploy.run(deploy.parse_args(["plan", *cli(tmp_path), "--inventory", str(inventory), "--scope", "all",
                                           "--what-if"]), az=fake)
    assert fake.calls == [], "no az invocation at all"
    assert [m["profiles"].get("health-model") for m in result["models"]] == [None, 1]
    assert result["models"][0]["whatIf"] == "skipped: offline inventory"


def test_models_command_lists_and_validates_definitions(tmp_path, capsys):
    assert deploy.main(["models"]) == 0
    listing = json.loads(capsys.readouterr().out)
    keys = [d["key"] for d in listing["definitions"]]
    assert keys == ["agents", "common", "project"]
    common = next(d for d in listing["definitions"] if d["key"] == "common")
    assert common["nests"] == ["project"] and common["layers"][1]["select"] == "nested model = project"
    (tmp_path / "broken.json").write_text(json.dumps({"key": "broken"}), encoding="utf-8")
    assert deploy.main(["models", "--model", str(tmp_path / "broken.json")]) == 1
    assert "token" in capsys.readouterr().err


def test_model_values_are_keys_unless_they_look_like_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents").write_text("not json", encoding="utf-8")
    assert deploy.main(["models", "--model", "agents"]) == 0, "a file named like a key must not shadow the key"
    assert deploy.main(["models", "--model", "nope"]) == 1
