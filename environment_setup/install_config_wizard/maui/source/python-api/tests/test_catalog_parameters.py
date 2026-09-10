import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import api, catalog_arm_schema, factory_catalog as catalog
from src.catalog_parameter_models import CatalogParameterPrepare, CatalogParameters
from src.catalog_parameters import ParameterService
from src.catalog_storage import CatalogError, database
from tests.test_catalog_runtime import OWNER, VERSION, root, harness


SECRET = "never-return-private-parameter-7192"
NESTED = [{"name": "service", "value": SECRET, "roles": ["reader"]}]
TEMPLATE = {
    "$schema": "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentTemplate.json#",
    "parameters": {
        "env": {"type": "string"},
        "operatorObjectId": {"type": "string", "minLength": 3},
        "kv-secret-objects": {"type": "array", "minLength": 1, "items": {"$ref": "#/definitions/Secret"}},
        "options": {"type": "secureObject", "additionalProperties": {"type": "string"}},
        "count": {"type": "int", "minValue": 1, "maxValue": 8, "defaultValue": 3},
        "enabled": {"type": "bool", "defaultValue": False},
        "tags": {"type": "object", "defaultValue": {}},
    },
    "definitions": {"Secret": {
        "type": "object", "properties": {
            "name": {"type": "string"}, "value": {"type": "secureString"},
            "roles": {"type": "array", "items": {"type": "string", "allowedValues": ["reader", "writer"]}},
        }, "required": ["name", "value", "roles"], "additionalProperties": False,
    }},
}


@pytest.fixture
def parameters(harness):
    service, runtime, factory, queue, records = harness
    templates = {"11-rgCommon": copy.deepcopy(TEMPLATE)}
    instance = ParameterService(service, compiler=lambda *args: copy.deepcopy(templates))
    context = {"factory_id": factory["id"], "scale_set_id": factory["scale_sets"][0]["id"], "version_ref": "124"}
    return instance, context, templates


def prepare_body(root, service, context, values=None, **extra):
    schema = service.read(str(root), **context)
    return {"folder": str(root), "contract_version": 1, **context, "expected_revision": schema["source_revision"],
            "schema_revision": schema["schema_revision"], "templates": [
                {"template": "11-rgCommon", "parameters": values if values is not None else
                 {"operatorObjectId": "explicit-owner", "kv-secret-objects": NESTED}}],
            **extra}


def save(root, service, body, owner=OWNER):
    preview = service.prepare(body, owner)
    return service.confirm(str(root), preview["confirmation_id"], owner)


def test_schema_form_required_identity_no_defaults_or_secret_values(root, parameters):
    service, context, _ = parameters
    result = CatalogParameters.model_validate(service.read(str(root), **context)).model_dump(mode="json")
    fields = {field["name"]: field for field in result["templates"][0]["fields"]}
    assert fields["operatorObjectId"] == {"name": "operatorObjectId", "required": True, "resolved": False,
                                          "configured": False, "sensitive": False}
    assert fields["kv-secret-objects"]["sensitive"]
    assert fields["env"]["resolved"] and fields["count"]["resolved"]
    assert "default" not in json.dumps(result["templates"][0]["parameter_schema"])
    assert not result["requires_profile_reset"]


def test_nested_values_durable_protected_and_runtime_schema_validated(root, parameters, harness):
    service, context, _ = parameters
    _, runtime, factory, queue, _ = harness
    before = (root / "variables.json").read_bytes()
    body = prepare_body(root, service, context)
    preview = service.prepare(body, OWNER)
    assert SECRET not in json.dumps(preview)
    path = service.planner.profile_path(root, factory, factory["scale_sets"][0])
    assert not path.exists()
    with database(root) as db:
        assert SECRET not in "\n".join(row["payload"] for row in db.execute("SELECT payload FROM confirmations"))
    result = service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert result["catalog"] is not None and result["job"] is None
    profile = service.planner._profile(SimpleNamespace(unprotect=runtime.unprotector), root, factory,
                                       factory["scale_sets"][0], VERSION)
    assert profile["parameters"]["11-rgCommon"]["kv-secret-objects"] == NESTED
    refreshed = service.read(str(root), **context)
    assert SECRET not in json.dumps(refreshed)
    fields = {item["name"]: item for item in refreshed["templates"][0]["fields"]}
    assert fields["kv-secret-objects"]["configured"] and fields["kv-secret-objects"]["resolved"]
    assert (root / "variables.json").read_bytes() == before
    assert not queue
    with database(root) as db:
        payload = json.loads(db.execute("SELECT payload FROM confirmations WHERE id=?", (preview["confirmation_id"],)).fetchone()[0])
        assert payload["sealed"] is None


@pytest.mark.parametrize("values", [
    {"unknown": SECRET}, {"count": "3"}, {"count": True}, {"count": 3.0}, {"count": 9}, {"enabled": 1},
    {"operatorObjectId": "x"}, {"kv-secret-objects": []},
    {"kv-secret-objects": [{"name": "x", "roles": ["reader"]}]},
    {"kv-secret-objects": [{"name": "x", "value": SECRET, "roles": ["owner"]}]},
    {"kv-secret-objects": [{"name": "x", "value": SECRET, "roles": ["reader"], "surprise": True}]},
    {"options": {"wrong": 123}}, {"env": "prod"},
    {"tags": {"aifactory.factory_id": "foreign-owner"}},
])
def test_schema_rejects_unknown_wrong_nested_constraints_and_identity(root, parameters, values):
    service, context, _ = parameters
    with pytest.raises(CatalogError) as error:
        service.prepare(prepare_body(root, service, context, values), OWNER)
    assert SECRET not in str(error.value)


def test_edits_preserve_other_values_and_project_contexts(root, parameters, harness):
    service, context, _ = parameters
    _, runtime, factory, _, _ = harness
    save(root, service, prepare_body(root, service, context))
    project_context = {**context, "project_id": factory["projects"][0]["id"]}
    save(root, service, prepare_body(root, service, project_context, {"operatorObjectId": "project-only"}))
    save(root, service, prepare_body(root, service, context, {"count": 5}))
    path = service.planner.profile_path(root, factory, factory["scale_sets"][0])
    stored = json.loads(runtime.unprotector(path.read_bytes()))
    assert stored["parameters"]["11-rgCommon"] == {"operatorObjectId": "explicit-owner", "kv-secret-objects": NESTED, "count": 5}
    assert stored["projects"][factory["projects"][0]["id"]]["parameters"]["11-rgCommon"] == {"operatorObjectId": "project-only"}
    effective = service.planner._profile(SimpleNamespace(unprotect=runtime.unprotector), root, factory,
                                         factory["scale_sets"][0], VERSION, project_id=factory["projects"][0]["id"])
    assert effective["parameters"]["11-rgCommon"]["operatorObjectId"] == "project-only"
    assert effective["parameters"]["11-rgCommon"]["count"] == 5


def test_owner_replay_schema_revision_and_source_drift_rejected(root, parameters, harness):
    service, context, templates = parameters
    preview = service.prepare(prepare_body(root, service, context), OWNER)
    with pytest.raises(CatalogError, match="authenticated"):
        service.confirm(str(root), preview["confirmation_id"], "another-owner")
    with pytest.raises(CatalogError, match="parameter configuration"):
        harness[0].confirm(str(root), preview["confirmation_id"], OWNER)
    templates["11-rgCommon"]["parameters"]["count"]["maxValue"] = 6
    with pytest.raises(CatalogError, match="schema changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    preview = service.prepare(prepare_body(root, service, context), OWNER)
    service.confirm(str(root), preview["confirmation_id"], OWNER)
    with pytest.raises(CatalogError, match="used or stale"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    body = prepare_body(root, service, context, {"count": 4})
    body["expected_revision"] = "f" * 64
    with pytest.raises(CatalogError, match="schema changed"):
        service.prepare(body, OWNER)


def test_new_source_requires_explicit_complete_profile_reset(root, parameters, harness):
    service, context, _ = parameters
    save(root, service, prepare_body(root, service, context))
    harness[1].resolver = lambda *args: {**VERSION, "resolved_ref": "c" * 40}
    read = service.read(str(root), **context)
    assert read["requires_profile_reset"]
    assert not any(field["configured"] for field in read["templates"][0]["fields"])
    body = prepare_body(root, service, context, {"count": 2})
    with pytest.raises(CatalogError, match="Explicitly review resetting"):
        service.prepare(body, OWNER)
    body["reset_profile"] = True
    save(root, service, body)
    path = service.planner.profile_path(root, harness[2], harness[2]["scale_sets"][0])
    stored = json.loads(harness[1].unprotector(path.read_bytes()))
    assert stored["source_commit"] == "c" * 40
    assert stored["parameters"] == {"11-rgCommon": {"count": 2}}


def test_unset_unknown_template_and_unenrolled_groups(root, parameters):
    service, context, _ = parameters
    save(root, service, prepare_body(root, service, context))
    body = prepare_body(root, service, context, {})
    body["templates"][0]["unset"] = ["operatorObjectId"]
    save(root, service, body)
    fields = service.read(str(root), **context)["templates"][0]["fields"]
    assert not next(field for field in fields if field["name"] == "operatorObjectId")["configured"]
    body = prepare_body(root, service, context)
    body["templates"][0]["template"] = "unpublished"
    with pytest.raises(CatalogError, match="published context"):
        service.prepare(body, OWNER)
    body["templates"][0]["template"] = "11-rgCommon"
    body["templates"][0]["resource_group_id"] = "/subscriptions/other/resourceGroups/foreign"
    with pytest.raises(CatalogError, match="exact writable"):
        service.prepare(body, OWNER)


def test_http_typed_schema_prepare_confirm_and_private_errors(root, parameters, monkeypatch):
    service, context, _ = parameters
    monkeypatch.setenv("AIFACTORY_API_KEY", "parameter-unit-key")
    monkeypatch.setattr(api, "_catalog_parameter_service", lambda: service)
    client = TestClient(api.app, client=("127.0.0.1", 12345))
    url = "/api/v1/factory-catalog/parameters"
    assert client.get(url, params={"folder": str(root), **context}).status_code == 401
    client.headers["X-API-Key"] = "parameter-unit-key"
    result = client.get(url, params={"folder": str(root), **context})
    assert result.status_code == 200, result.text
    body = prepare_body(root, service, context)
    preview = client.post(url + "/prepare", json=body)
    assert preview.status_code == 200, preview.text
    assert SECRET not in preview.text
    confirmed = client.post(url + "/confirm", json={"folder": str(root), "contract_version": 1,
                                                   "confirmation_id": preview.json()["confirmation_id"]})
    assert confirmed.status_code == 200, confirmed.text
    body["extra"] = SECRET
    response = client.post(url + "/prepare", json=body)
    assert response.status_code == 422 and SECRET not in response.text
    remote = TestClient(api.app, client=("198.51.100.9", 12345), headers=client.headers)
    assert remote.get(url, params={"folder": str(root), **context}).status_code == 403


def test_schema_references_are_offline_and_nonfinite_values_rejected():
    with pytest.raises(CatalogError, match="reference"):
        catalog_arm_schema.parameter_schema({"secret": {"$ref": "https://untrusted.example/secret-schema"}})
    schema = catalog_arm_schema.parameter_schema({"items": {"type": "object"}})
    with pytest.raises(CatalogError, match="schema"):
        catalog_arm_schema.validate_values(schema, {"items": {"value": float("nan")}})
    CatalogParameterPrepare.model_json_schema()


@pytest.mark.parametrize(("definition", "valid", "invalid"), [
    ({"type": "object", "properties": {"required": {"type": "string"}, "optional": {"type": "int", "nullable": True}}},
     {"required": "yes"}, {"optional": 1}),
    ({"type": "array", "prefixItems": [{"type": "int"}, {"type": "bool"}], "items": False},
     [1, True], [1]),
    ({"type": "array", "allowedValues": ["reader", "writer"]}, ["reader", "writer"], ["admin"]),
    ({"type": "object", "discriminator": {"propertyName": "type", "mapping": {
        "ints": {"type": "object", "additionalProperties": {"type": "int"}},
        "strings": {"type": "object", "additionalProperties": {"type": "string"}}}}},
     {"type": "ints", "foo": 1}, {"type": "ints", "foo": "wrong"}),
])
def test_arm_aggregate_semantics_not_generic_json_schema_defaults(definition, valid, invalid):
    schema = catalog_arm_schema.parameter_schema({"data": definition})
    catalog_arm_schema.validate_values(schema, {"data": valid})
    with pytest.raises(CatalogError):
        catalog_arm_schema.validate_values(schema, {"data": invalid})


def test_compilation_uses_only_verified_published_templates_without_cloud_identity(root, parameters):
    service, _, _ = parameters
    source = root / "published-source"
    source.mkdir()
    paths = {name: name + ".bicep" for name in ("11-rgCommon", "12-networkCommon", "13-rgLevel")}
    for path in paths.values():
        (source / path).write_text("parameter-test", encoding="utf-8")
    calls = []
    def read(tool, arguments, **kwargs):
        calls.append((tool, arguments))
        assert tool in ("git", "az")
        if tool == "git":
            assert arguments[-3:] == ["status", "--porcelain", "--untracked-files=no"] or "ls-files" in arguments
            return ""
        if arguments == ["bicep", "version"]:
            return "Bicep version 1.0.0"
        assert arguments[:3] == ["bicep", "build", "--file"] and arguments[-1] == "--stdout"
        return copy.deepcopy(TEMPLATE)
    def verify(cloud, selected_source, metadata):
        assert selected_source == source and metadata["commit"] == VERSION["resolved_ref"]
        cloud.command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=str(source))
    module = SimpleNamespace(COMMON_TEMPLATES=paths, PROJECT_TEMPLATES=set(), Blocked=CatalogError, verify_source=verify)
    service.planner.module = lambda *args: (module, source)
    service.runtime.cli = SimpleNamespace(read=read)
    service._compile_template = lambda source, path: read("az", ["bicep", "build", "--file", str(path), "--stdout"])
    result = service._compile(root, VERSION, None, {})
    assert set(result) == set(paths)
    assert [tool for tool, _ in calls] == ["git", "az", "git", "az", "git", "az", "git", "az", "git"]


def test_expiration_profile_drift_and_dpapi_failure_are_not_success(root, parameters, harness):
    service, context, _ = parameters
    body = prepare_body(root, service, context)
    preview = service.prepare(body, OWNER)
    service.service.clock = lambda: 1000
    with pytest.raises(CatalogError, match="expired"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    service.service.clock = lambda: 100
    preview = service.prepare(body, OWNER)
    save(root, service, body)
    with pytest.raises(CatalogError, match="stale"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    body = prepare_body(root, service, context)
    harness[1].protector = lambda data: (_ for _ in ()).throw(ValueError(SECRET))
    with pytest.raises(CatalogError, match="DPAPI") as error:
        service.prepare(body, OWNER)
    assert SECRET not in str(error.value)


def test_exact_enrolled_group_and_template_spec_choices_can_be_saved(root, parameters, harness):
    from tests.test_catalog_runtime import RG
    service, context, templates = parameters
    templates["11-rgCommon"]["$schema"] = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
    common = RG + "-shared"
    spec = common + "/providers/Microsoft.Resources/templateSpecs/compiled-common/versions/1"
    service._binding = lambda *args: ([RG], [common])
    schema = service.read(str(root), **context)
    assert schema["templates"][0]["resource_group_ids"] == [RG]
    body = prepare_body(root, service, context, {})
    body["templates"][0].update(resource_group_id=RG, template_spec_id=spec)
    save(root, service, body)
    path = service.planner.profile_path(root, harness[2], harness[2]["scale_sets"][0])
    profile = json.loads(harness[1].unprotector(path.read_bytes()))
    assert profile["resource_groups"]["11-rgCommon"] == RG
    assert profile["template_spec_ids"]["11-rgCommon"] == spec
    body = prepare_body(root, service, context, {})
    body["templates"][0]["template_spec_id"] = spec.rsplit("/", 1)[0] + "/.."
    with pytest.raises(CatalogError, match="immutable template-spec"):
        service.prepare(body, OWNER)


def test_new_factory_without_projects_has_a_working_common_parameter_form(root, parameters, harness):
    service, _, _ = parameters
    catalog_service, _, factory, _, _ = harness
    scale = {key: factory["scale_sets"][0][key] for key in
             ("environment", "suffix", "subscription_id", "tenant_id", "orchestrator", "network")}
    preview = catalog_service.prepare({"folder": str(root), "contract_version": 1, "action": "create-factory",
                                        "target_prefix": "fresh-", "target_region": "swedencentral", "scale_sets": [scale]}, OWNER)
    assert preview["can_execute"], preview["blockers"]
    catalog_service.confirm(str(root), preview["confirmation_id"], OWNER)
    created = preview["target"]
    assert created["projects"] == []
    context = {"factory_id": created["id"], "scale_set_id": created["scale_sets"][0]["id"]}
    body = prepare_body(root, service, context, {"operatorObjectId": "new-explicit-owner", "kv-secret-objects": NESTED})
    result = save(root, service, body)
    assert result["catalog"] is not None and result["job"] is None
    schema = service.read(str(root), **context)
    assert next(field for field in schema["templates"][0]["fields"] if field["name"] == "operatorObjectId")["resolved"]


def test_nested_secure_schema_marks_field_sensitive_even_without_secret_name(root, parameters):
    service, context, templates = parameters
    templates["11-rgCommon"]["parameters"]["payload"] = {"type": "object", "properties": {
        "nested": {"type": "secureString"}}}
    schema = service.read(str(root), **context)["templates"][0]
    assert next(field for field in schema["fields"] if field["name"] == "payload")["sensitive"]
    assert schema["parameter_schema"]["properties"]["env"]["readOnly"]
    assert schema["parameter_schema"]["properties"]["payload"]["properties"]["nested"]["writeOnly"]


def test_unknown_factory_never_inherits_a_foreign_root_version(root, parameters, harness):
    service, context, _ = parameters
    document = catalog.load_document(root)
    document["factories"][0].update(aifactory_version=None, version_ref=None)
    catalog.commit_document(root, document)
    context.pop("version_ref")
    with pytest.raises(CatalogError, match="explicitly select"):
        service.read(str(root), **context)
    request = {"folder": str(root), "contract_version": 1, "action": "deploy", **context}
    preview = harness[0].prepare(request, OWNER)
    assert not preview["can_execute"] and "explicitly select" in " ".join(preview["blockers"])


@pytest.mark.parametrize(("kind", "default"), [("secureString", SECRET), ("secureObject", {"value": SECRET})])
def test_published_credential_defaults_do_not_fill_missing_secrets(root, parameters, kind, default):
    service, context, templates = parameters
    templates["11-rgCommon"]["parameters"]["explicitCredential"] = {"type": kind, "defaultValue": default}
    result = service.read(str(root), **context)
    field = next(item for item in result["templates"][0]["fields"] if item["name"] == "explicitCredential")
    assert field["required"] and field["sensitive"]
    assert not field["resolved"] and not field["configured"]
    assert SECRET not in json.dumps(result)
    save(root, service, prepare_body(root, service, context, {"explicitCredential": default}))
    result = service.read(str(root), **context)
    assert next(item for item in result["templates"][0]["fields"] if item["name"] == "explicitCredential")["resolved"]
