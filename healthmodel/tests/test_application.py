"""Application layer: the HealthModelService facade with commands and events, on a fake infrastructure family."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aifactory_healthmodel import naming
from aifactory_healthmodel.application.commands import AnnotateModelCommand, CommandInvoker, LazyClient
from aifactory_healthmodel.application.events import (CommandExecuted, ConsoleReporter, EventBus, ModelPlanned,
                                                      PipelineReporter, RunCompleted, RunStarted, WarningRaised)
from aifactory_healthmodel.application.ports import CallableClientFactory, ClientFactory, TemplateDeployer
from aifactory_healthmodel.application.service import HealthModelService, RunRequest
from aifactory_healthmodel.bootstrap import Settings, create_services
from aifactory_healthmodel.client import HealthModelError
from aifactory_healthmodel.infrastructure.offline import OfflineInfrastructure
from aifactory_healthmodel.infrastructure.proxies import ReadOnlyViolation

SUB = "00000000-0000-0000-0000-0000000000aa"
TENANT = "11111111-1111-1111-1111-111111111111"
PRJ, CMN = "spider-esml-project001-sdc-dev-001-rg", "spider-esml-common-sdc-dev-001"


def factory_scope():
    return naming.explicit(tenant_id=TENANT, subscription_id=SUB, environment="dev", project_number="001",
                           location="swedencentral", location_suffix="sdc", project_resource_group=PRJ,
                           common_resource_group=CMN, resource_group_prefix="spider-", resource_group_suffix="-001")


class RecordingDeployer:
    def __init__(self):
        self.deployed, self.what_ifs = [], []

    def what_if(self, resource_group, template, parameters):
        self.what_ifs.append(resource_group)
        return {"NoChange": 3}

    def deploy(self, name, resource_group, template, parameters):
        self.deployed.append((name, resource_group, json.loads(Path(parameters).read_text(encoding="utf-8"))))
        return {"properties": {"provisioningState": "Succeeded"}}


class FakeClient:
    log: list = []

    def __init__(self, model_id, transport):
        self.model_id = model_id
        FakeClient.log.append(("client", model_id.rsplit("/", 1)[-1]))

    def stale_managed(self, entities, relationships):
        return {"entities": ["old-entity"], "relationships": ["layer-x-to-old-entity"]}

    def delete_relationship(self, name):
        FakeClient.log.append(("delete-relationship", name))

    def delete_entity(self, name):
        FakeClient.log.append(("delete-entity", name))

    def add_annotation(self, entity, details, description=None):
        FakeClient.log.append(("annotate", details["definition"]))


class WritableInventory(OfflineInfrastructure):
    """Offline discovery with a recording deployer: a test family that may 'deploy'."""

    supports_writes = True

    def __init__(self, rows, registered=True):
        super().__init__(rows, subscription_id=SUB, tenant_id=TENANT,
                         registration="Registered" if registered else "NotRegistered")
        self.deployer = RecordingDeployer()
        self.registrations = 0
        family = self

        class Providers:
            def provider(self):
                return {"registrationState": family.registration, "regions": set()}

            def register_provider(self, timeout=600):
                family.registrations += 1
                family.registration = "Registered"

        self._providers = Providers()

    def create_deployer(self):
        return self.deployer

    def create_provider_registrar(self, transport):
        return self._providers


class Untouchable:
    def verify_account(self, tenant_id):
        raise AssertionError("Azure must not be called")


class AzureMustNotBeCalled(WritableInventory):
    """Fails the test as soon as the run makes its first Azure call (the account check)."""

    def create_account_verifier(self):
        return Untouchable()


def write_definition(folder: Path, **document) -> Path:
    folder.mkdir(exist_ok=True)
    (folder / f"{document['key']}.json").write_text(json.dumps(document), encoding="utf-8")
    return folder


def health_model_rows(*models):
    return [{"id": f"/subscriptions/{SUB}/resourceGroups/{group}/providers/Microsoft.CloudHealth/healthmodels/{name}",
             "name": name, "type": "microsoft.cloudhealth/healthmodels", "resourceGroup": group, "kind": "",
             "tags": {}} for name, group in models]


@pytest.fixture()
def run(tmp_path, test_env_resources):
    FakeClient.log = []

    def runner(mode, models, family=None, events=None, definitions_dirs=(), scope=None, **request):
        family = family or WritableInventory(test_env_resources)
        provider = create_services(
            Settings(subscription_id=SUB, tenant_id=TENANT, read_only=mode == "plan", resilience=False,
                     pipeline_annotations=False, definitions_dirs=tuple(definitions_dirs)),
            infrastructure=family,
            configure=lambda services: services.replace(ClientFactory, instance=CallableClientFactory(FakeClient)))
        bus = provider.get(EventBus)
        if events is not None:
            bus.subscribe(object, events.append)
        service = provider.get(HealthModelService)
        result = service.run(RunRequest(mode=mode, scope=scope or factory_scope(), models=tuple(models),
                                        work_root=tmp_path, **request))
        return result, family

    return runner


def test_plan_orders_models_and_previews_writes_without_deploying(run, tmp_path):
    result, family = run("plan", ["common", "agents", "project"], what_if=True)
    assert [m["definition"] for m in result["models"]] == ["agents", "project", "common"]
    assert family.deployer.deployed == [] and all(m["azureWritesPerformed"] is False for m in result["models"])
    assert family.deployer.what_ifs == [PRJ, PRJ, CMN] and result["models"][0]["whatIf"] == {"NoChange": 3}
    project = result["models"][1]
    assert project["writes"][0].startswith("Deploy health model hm-spider-prj001-sdc-dev-001 to resource group")
    assert any("annotation" in w for w in project["writes"])
    assert not list(tmp_path.glob(".healthmodel-*")), "the work folder is removed"


def test_common_model_nests_models_planned_in_the_same_run(run):
    alone, _ = run("plan", ["common"])
    together, _ = run("plan", ["project", "common"])
    assert alone["models"][0]["profiles"].get("health-model") is None
    assert together["models"][1]["profiles"]["health-model"] == 1


def test_plan_mode_is_protected_by_read_only_proxies(test_env_resources):
    provider = create_services(Settings(subscription_id=SUB, tenant_id=TENANT, read_only=True, resilience=False,
                                        pipeline_annotations=False),
                               infrastructure=WritableInventory(test_env_resources))
    with pytest.raises(ReadOnlyViolation):
        provider.get(TemplateDeployer).deploy("n", "rg", Path("t"), Path("p"))


def test_deploy_runs_commands_in_order_and_publishes_events(run):
    events = []
    result, family = run("deploy", ["project", "common"], events=events, prune=True, run_id="42")
    assert [d[1] for d in family.deployer.deployed] == [PRJ, CMN]
    assert family.deployer.deployed[0][0] == "aifactory-hm-spider-prj001-sdc-dev-001"
    assert FakeClient.log == [
        ("client", "hm-spider-prj001-sdc-dev-001"), ("delete-relationship", "layer-x-to-old-entity"),
        ("delete-entity", "old-entity"), ("annotate", "project"),
        ("client", "hm-spider-cmn-sdc-dev-001"), ("delete-relationship", "layer-x-to-old-entity"),
        ("delete-entity", "old-entity"), ("annotate", "common")]
    assert result["models"][0]["pruned"]["entities"] == ["old-entity"]
    assert result["models"][1]["healthModelId"].endswith("/healthmodels/hm-spider-cmn-sdc-dev-001")
    kinds = [type(e).__name__ for e in events]
    assert kinds[0] == "RunStarted" and kinds[-1] == "RunCompleted"
    assert kinds.count("ModelPlanned") == 2 and kinds.count("CommandExecuted") == 6
    assert events[-1].writes == 6


def test_deploy_requires_a_registered_provider_or_explicit_registration(run, test_env_resources):
    family = WritableInventory(test_env_resources, registered=False)
    with pytest.raises(RuntimeError, match="--register-provider"):
        run("deploy", ["project"], family=family)
    assert family.deployer.deployed == []
    result, family = run("deploy", ["project"], family=WritableInventory(test_env_resources, registered=False),
                         register_provider=True, annotate=False)
    assert family.registrations == 1 and result["models"][0]["providerRegistration"] == "Registered"


def test_offline_family_refuses_to_deploy(run, test_env_resources):
    offline = OfflineInfrastructure(test_env_resources, subscription_id=SUB, tenant_id=TENANT)
    with pytest.raises(RuntimeError, match="offline"):
        run("deploy", ["project"], family=offline)
    result, _ = run("plan", ["project"], family=offline, what_if=True)
    assert result["models"][0]["whatIf"] == "skipped: offline inventory"


def test_definition_defaults_merge_with_run_options(run):
    result, family = run("deploy", ["agents"], annotate=False, options={"alertPolicy": {"rootDegradedSeverity": ""}})
    parameters = family.deployer.deployed[0][2]["parameters"]
    assert parameters["alertPolicy"]["value"] == {"rootUnhealthySeverity": "Sev1", "rootDegradedSeverity": "",
                                                  "layerUnhealthySeverity": "Sev2"}
    assert result["models"][0]["alertPolicy"]["rootDegradedSeverity"] == ""


@pytest.mark.parametrize("request_fields,message", [
    ({"overrides": {"profiles": {"nope": {}}}}, "unknown profile"),
    ({"overrides": {"signals": {"foundry/throttled-calls": {"unhealthyThreshold": "high"}}}}, "integers"),
    ({"workspace_id": "/subscriptions/x/resourceGroups/y/providers/Microsoft.Storage/storageAccounts/z"}, "workspace"),
    ({"options": {"notAParameter": 1}}, "option"),
    ({"options": {"alertPolicy": {"rootUnhealthySeverity": "Sev9"}}}, "severity"),
    ({"options": {"healthObjective": 120}}, "healthObjective"),
])
def test_invalid_inputs_fail_before_any_azure_call(run, test_env_resources, request_fields, message):
    family = AzureMustNotBeCalled(test_env_resources, registered=False)
    with pytest.raises(ValueError, match=message):
        run("deploy", ["project", "common"], family=family, register_provider=True, **request_fields)
    assert family.deployer.deployed == [] and family.registrations == 0


def test_every_model_is_validated_before_the_first_azure_call(run, tmp_path, test_env_resources):
    """Overrides valid on their own but invalid once merged must not leave earlier models deployed."""
    folder = write_definition(tmp_path / "definitions", key="tuned", nameToken="tun{project}", home="project",
                              rootDisplayName="Tuned {project}",
                              layers=[{"fromCatalog": True, "select": {"origin": "project"}}],
                              overrides={"signals": {"foundry/throttled-calls": {"degradedThreshold": 50}}})
    family = AzureMustNotBeCalled(test_env_resources, registered=False)
    with pytest.raises(ValueError, match="before the unhealthy"):
        run("deploy", ["project", "tuned"], family=family, definitions_dirs=(folder,), register_provider=True,
            overrides={"signals": {"foundry/throttled-calls": {"unhealthyThreshold": 40}}})
    assert family.deployer.deployed == [] and family.registrations == 0


def test_a_common_model_without_a_common_resource_group_fails_before_azure(run, test_env_resources):
    scope = naming.explicit(tenant_id=TENANT, subscription_id=SUB, environment="dev", project_number="001",
                            location="swedencentral", location_suffix="sdc", project_resource_group=PRJ)
    family = AzureMustNotBeCalled(test_env_resources)
    with pytest.raises(ValueError, match="no common resource group"):
        run("deploy", ["project", "common"], family=family, scope=scope)
    assert family.deployer.deployed == []


def test_a_definition_plans_the_same_model_whatever_else_runs(run, tmp_path, test_env_resources):
    folder = write_definition(tmp_path / "definitions", key="everything", nameToken="all{project}", home="project",
                              rootDisplayName="Everything {project}",
                              layers=[{"fromCatalog": True, "select": {"all": True}}])
    rows = [*test_env_resources, *health_model_rows(
        ("hm-spider-prj001-sdc-dev-001", PRJ), ("hm-spider-agt001-sdc-dev-001", PRJ),
        ("hm-spider-prj002-sdc-dev-001", "spider-esml-project002-sdc-dev-001-rg"))]
    summaries = []
    for models in (["everything"], ["everything", "common"], ["project", "everything"]):
        result, _ = run("plan", models, family=WritableInventory(rows), definitions_dirs=(folder,))
        model = next(m for m in result["models"] if m["definition"] == "everything")
        summaries.append({key: model[key] for key in ("entities", "profiles", "readerResourceGroups")})
    assert summaries[0] == summaries[1] == summaries[2]
    assert "health-model" not in summaries[0]["profiles"], "only definitions named by nestedModel are nested"
    common = run("plan", ["common"], family=WritableInventory(rows))[0]["models"][0]
    assert common["profiles"]["health-model"] == 2, "the common model still nests both project models"


def test_command_invoker_keeps_an_audit_history():
    bus, seen = EventBus(), []
    bus.subscribe(CommandExecuted, seen.append)
    invoker = CommandInvoker(bus)

    class Echo:
        def describe(self):
            return "echo"

        def execute(self):
            return 7

    assert invoker.execute(Echo()) == 7
    assert [c.describe() for c in invoker.history] == ["echo"] and seen == [CommandExecuted("echo")]


def test_annotation_failures_become_warnings_not_errors():
    bus, warnings = EventBus(), []
    bus.subscribe(WarningRaised, warnings.append)

    class Failing:
        def add_annotation(self, *args, **kwargs):
            raise HealthModelError("nope", "AuthorizationFailed", 403)

    plan = type("P", (), {"model_name": "hm-x", "definition": "project", "entities": []})()
    AnnotateModelCommand(lambda: Failing(), plan, "local", bus).execute()
    assert warnings == [WarningRaised("deployment annotation skipped (AuthorizationFailed).")]


def test_lazy_client_is_a_virtual_proxy():
    created = []

    def factory():
        created.append(1)
        return type("C", (), {"ping": lambda self: "pong"})()

    lazy = LazyClient(factory)
    assert created == []
    assert lazy.ping() == "pong" and lazy.ping() == "pong" and created == [1]


def test_reporters_observe_the_event_bus(capsys):
    bus = EventBus()
    ConsoleReporter().attach(bus)
    PipelineReporter("github").attach(bus)
    bus.publish(RunStarted("plan", ("project",), SUB))
    bus.publish(ModelPlanned("project", "hm-x", 3, 5, ("Line one\nline two",)))
    bus.publish(WarningRaised("annotation skipped"))
    bus.publish(RunCompleted("plan", ("project",), 0))
    out, err = capsys.readouterr()
    assert "::warning title=Health model hm-x::Line one%0Aline two" in out
    assert "WARNING: annotation skipped" in err
    ado = PipelineReporter("azure-devops")
    ado.attach(bus)
    bus.publish(WarningRaised("x"))
    assert "##vso[task.logissue type=warning]x" in capsys.readouterr().out
    assert PipelineReporter.detect({"GITHUB_ACTIONS": "true"}).flavour == "github"
    assert PipelineReporter.detect({"TF_BUILD": "True"}).flavour == "azure-devops"
    assert PipelineReporter.detect({}) is None


def test_definition_defaults_are_validated_with_the_run_options(run, tmp_path, test_env_resources):
    folder = write_definition(tmp_path / "definitions", key="tuned", nameToken="tun{project}", home="project",
                              rootDisplayName="Tuned {project}", healthObjective=95,
                              layers=[{"fromCatalog": True, "select": {"origin": "project"}}],
                              alertPolicy={"rootUnhealthySeverity": "Sev2"})
    result, family = run("deploy", ["tuned"], definitions_dirs=(folder,), annotate=False,
                         options={"alertPolicy": {"rootDegradedSeverity": ""}})
    parameters = family.deployer.deployed[0][2]["parameters"]
    assert parameters["healthObjective"]["value"] == 95
    assert parameters["alertPolicy"]["value"] == {"rootUnhealthySeverity": "Sev2", "rootDegradedSeverity": ""}
