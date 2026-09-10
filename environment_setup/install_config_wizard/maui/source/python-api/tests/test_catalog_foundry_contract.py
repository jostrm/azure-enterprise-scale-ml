import copy
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace, ModuleType
from uuid import uuid4

import pytest

from src import catalog_protocol as protocol, factory_catalog as catalog
from src.catalog_frozen_plan import FrozenPlanner
from src.catalog_parameters import ParameterService, IMMUTABLE
from src.catalog_storage import CatalogError
from src.simple_mode import ReadOnlyCLI
from src.ticket_connectors import TicketError
from tests.test_catalog_runtime import OWNER, VERSION, SUB, TENANT, RG, root, harness, deploy_request
from tests.test_catalog_frozen_plan import scoped


FIXTURES = Path(__file__).parent / "fixtures"
METADATA = json.loads((FIXTURES / "foundry-v4-compiled.metadata.json").read_text(encoding="utf-8"))
FOUNDRY = METADATA["template"]


@pytest.fixture
def compiled():
    raw = gzip.decompress((FIXTURES / METADATA["fixture"]).read_bytes())
    value = json.loads(raw)
    assert len(raw) == METADATA["compiled_bytes"] > 2_000_000
    assert protocol.fingerprint(value) == METADATA["compiled_sha256"]
    assert len(value["parameters"]) == METADATA["parameter_count"] == 84
    return value


@pytest.fixture
def canonical():
    root = Path(os.environ.get("AIFACTORY_LIFECYCLE_SOURCE_ROOT", str(
        Path(__file__).parents[2] / "003_aifactory_sub" / "azure-enterprise-scale-ml")))
    helper = root / "bootstrap" / "lib" / "factory_lifecycle.py"
    if not helper.is_file():
        pytest.skip("Set AIFACTORY_LIFECYCLE_SOURCE_ROOT for the canonical runtime cross-contract tests.")
    module = ModuleType("catalog_foundry_runtime_test")
    module.__file__ = str(helper)
    exec(compile(helper.read_bytes(), str(helper), "exec"), module.__dict__)
    return module, root


def reviewed_values(template):
    values = {}
    for name, definition in template["parameters"].items():
        if name in IMMUTABLE or name in ("tags", "tagsProject"):
            continue
        if "defaultValue" in definition and not (
                isinstance(definition["defaultValue"], str) and definition["defaultValue"].startswith("[")):
            values[name] = copy.deepcopy(definition["defaultValue"])
        else:
            assert definition["type"] == "string", "Review newly required non-string fixture inputs explicitly."
            values[name] = "explicit-fixture-" + name
    values["enableAIFoundry"] = True
    return values


def test_actual_foundry_schema_maps_only_tags_project_and_selected_subscription(compiled):
    target = {"factory_id": str(uuid4()), "scaleset_id": str(uuid4()), "environment": "stage",
              "region": "swedencentral", "prefix": "fixture-", "suffix": "002", "subscription_id": SUB, "tenant_id": TENANT}
    logical = str(uuid4())
    variables = {"tagsProject": json.dumps({"application": "reviewed", "aifactory.logical_project_id": logical}),
                 "unconsumed_configuration": {"nested": ["retained"]}}
    before = copy.deepcopy(variables)
    result = FrozenPlanner.parameters(compiled["parameters"], variables, reviewed_values(compiled), target, "017")
    assert set(result) == set(compiled["parameters"])
    assert "tags" not in result and "tags" not in compiled["parameters"]
    assert result["tagsProject"] == {"application": "reviewed", "aifactory.logical_project_id": logical,
                                     "aifactory.factory_id": target["factory_id"], "aifactory.scaleset_id": target["scaleset_id"],
                                     "aifactory.project_id": "017"}
    assert result["subscriptionIdDevTestProd"] == SUB
    assert result["env"] == "test" and result["projectNumber"] == "017"
    assert variables == before


@pytest.mark.parametrize("profile", [{}, {"costCenter": "123456", "application": "reviewed override"}])
@pytest.mark.parametrize("serialized", [False, True])
def test_actual_foundry_preserves_source_and_profile_customer_tags(compiled, profile, serialized):
    target = {"factory_id": str(uuid4()), "scaleset_id": str(uuid4()), "environment": "dev",
              "region": "swedencentral", "prefix": "fixture-", "suffix": "001", "subscription_id": SUB, "tenant_id": TENANT}
    logical = str(uuid4())
    source_tags = {"application": "source", "customerTeam": "platform", "aifactory.logical_project_id": logical}
    variables = {"tagsProject": json.dumps(source_tags) if serialized else source_tags}
    overrides = {**reviewed_values(compiled), "tagsProject": json.dumps(profile) if serialized else profile}
    before = copy.deepcopy((variables, overrides))
    result = FrozenPlanner.parameters(compiled["parameters"], variables, overrides, target, "017")
    assert set(result) == set(compiled["parameters"]) and "tags" not in result
    assert result["tagsProject"] == {**source_tags, **profile, "aifactory.factory_id": target["factory_id"],
                                     "aifactory.scaleset_id": target["scaleset_id"], "aifactory.project_id": "017"}
    assert (variables, overrides) == before


@pytest.mark.parametrize("key", ["aifactory.factory_id", "aifactory.scaleset_id",
                                  "aifactory.project_id", "aifactory.logical_project_id"])
@pytest.mark.parametrize("uppercase", [False, True])
def test_actual_foundry_rejects_profile_ownership_conflicts(compiled, key, uppercase):
    target = {"factory_id": str(uuid4()), "scaleset_id": str(uuid4()), "environment": "dev",
              "region": "swedencentral", "prefix": "fixture-", "suffix": "001", "subscription_id": SUB, "tenant_id": TENANT}
    variables = {"tagsProject": {"customerTeam": "platform", "aifactory.logical_project_id": str(uuid4())}}
    overrides = {**reviewed_values(compiled), "tagsProject": {key.upper() if uppercase else key: "conflicting-owner"}}
    with pytest.raises(CatalogError, match="ownership"):
        FrozenPlanner.parameters(compiled["parameters"], variables, overrides, target, "017")


def test_real_foundry_exceeds_generic_reader_but_bounded_compiler_preserves_every_field(root, harness, compiled):
    service, runtime, *_ = harness
    raw = gzip.decompress((FIXTURES / METADATA["fixture"]).read_bytes()).decode("utf-8")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=raw, stderr="")
    runtime.cli = ReadOnlyCLI(runner=run)
    with pytest.raises(TicketError) as error:
        runtime.cli.read("az", ["bicep", "build", "--stdout"])
    assert "size" in str(error.value).lower() or "large" in str(error.value).lower()
    result = ParameterService(service)._compile_template(root, root / "declared-template.bicep")
    assert result == compiled
    argv, options = calls[-1]
    assert argv == ["az", "bicep", "build", "--file", str(root / "declared-template.bicep"), "--stdout"]
    assert options["shell"] is False and options["timeout"] == 120
    assert "AIFACTORY_API_KEY" not in options["env"]
    assert "parameters" in result and "resources" in result and "variables" in result


def test_bicep_transport_keeps_its_runtime_bound_and_redacts_errors(root, harness):
    service, runtime, *_ = harness
    runtime.cli = ReadOnlyCLI(runner=lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="x" * (8 * 1024 * 1024 + 1), stderr=""))
    with pytest.raises(CatalogError, match="8 MiB"):
        ParameterService(service)._compile_template(root, root / "template.bicep")
    runtime.cli = ReadOnlyCLI(runner=lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout="", stderr="sensitive-compiler-detail"))
    with pytest.raises(CatalogError) as error:
        ParameterService(service)._compile_template(root, root / "template.bicep")
    assert "sensitive-compiler-detail" not in str(error.value)


@pytest.mark.parametrize("environment", ["dev", "stage", "prod"])
def test_backend_foundry_plan_with_actual_compiled_template_real_validator_and_phase_ids(
        root, harness, compiled, canonical, monkeypatch, environment):
    _, runtime, factory, _, _ = harness
    module, source = canonical
    document = catalog.load_document(root)
    scale = factory["scale_sets"][0]
    scale["environment"] = environment
    command = deploy_request(root, factory)
    scoped(runtime)
    binding = runtime.binding(root, factory, scale)
    config = runtime._configuration(factory, [scale], document, command)
    section = "dev" if environment == "dev" else "stage_prod"
    config["targets"][scale["id"]][section].update(
        useSelfHostedBuildAgent="false", retained_structured_setting={"values": [True, 17, {"keep": "all"}]})
    source_tags = json.loads(config["targets"][scale["id"]][section]["tagsProject"])
    config["targets"][scale["id"]][section]["tagsProject"] = json.dumps({**source_tags, "customerTeam": "platform"})
    manifest = protocol.manifest(str(uuid4()), factory, scale, command, VERSION, config, binding,
                                 runtime.inventory(root, factory, [scale]), [], catalog.utc(100), catalog.utc(700), frozen=True)
    manifest["identity"]["deployment_object_id"] = TENANT
    original_config = copy.deepcopy(manifest["config"])
    traffic = []
    def request(method, url, audience, **kwargs):
        traffic.append((method, url, kwargs.get("data")))
        assert method == "POST" and "/whatIf?" in url
        return 200, {}, {"status": "Succeeded", "properties": {"changes": [
            {"resourceId": RG, "changeType": "NoChange", "before": {"id": RG}, "after": {"id": RG}}]}}
    cloud = SimpleNamespace(compile_template=lambda selected, path: copy.deepcopy(compiled),
                            verify_identity=lambda **kwargs: None, request=request)
    monkeypatch.setattr(module, "verify_source", lambda cloud, selected, metadata: selected)
    adapter = SimpleNamespace(COMMON_TEMPLATES=module.COMMON_TEMPLATES, PROJECT_TEMPLATES={FOUNDRY},
                              digest=module.digest, validate_deployment_plan=module.validate_deployment_plan,
                              freeze_deployment_plan=module.freeze_deployment_plan)
    planner = FrozenPlanner(runtime)
    planner._profile = lambda *args, **kwargs: {"parameters": {Path(FOUNDRY).stem: {
                                                  **reviewed_values(compiled), "tagsProject": {"costCenter": "123456"}}},
                                               "resource_groups": {}, "template_spec_ids": {}}
    planner._deployment(adapter, cloud, root, factory, scale, manifest, source, VERSION)
    module.validate_deployment_plan(manifest)
    step = manifest["deployment"]["steps"][0]
    assert step["id"] == "step-09-ai-foundry-2025-v4"
    assert step["template_hash"] == METADATA["compiled_sha256"]
    assert set(step["parameters"]) == set(compiled["parameters"])
    assert "tags" not in step["parameters"]
    assert step["parameters"]["tagsProject"]["aifactory.logical_project_id"] == command["project_id"]
    assert step["parameters"]["tagsProject"]["customerTeam"] == "platform"
    assert step["parameters"]["tagsProject"]["costCenter"] == "123456"
    assert manifest["config"] == original_config
    assert manifest["deployment"]["configuration_hash"] == module.digest(original_config)
    assert len(traffic) == 1
    combined = traffic[0][2]["properties"]["template"]
    assert combined["resources"][0]["properties"]["template"] == compiled
    names = []
    for path in [*module.COMMON_TEMPLATES.values(), *sorted(module.PROJECT_TEMPLATES)]:
        phase = {**step, "id": "step-" + Path(path).stem}
        name = module.deployment_endpoint(manifest, phase).rsplit("/", 1)[1]
        assert len(name) <= 64
        names.append(name)
    assert len(names) == len(set(names))
    injected = copy.deepcopy(manifest)
    injected["deployment"]["steps"][0]["parameters"]["tags"] = step["parameters"]["tagsProject"]
    with pytest.raises(module.Blocked, match="parameters-not-fully-resolved"):
        module.compiled_plan_step(cloud, injected, injected["deployment"]["steps"][0], source)
