"""Pipeline inputs must resolve without an API, Azure login or filesystem writes."""

import copy
import importlib
import json
import socket
import stat
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
inputs = importlib.import_module("pipeline_inputs")
FACTORY = "11111111-1111-4111-8111-111111111111"
SCALE = "22222222-2222-4222-8222-222222222222"
PROJECT = "33333333-3333-4333-8333-333333333333"
TENANT = "44444444-4444-4444-8444-444444444444"
SUB = "55555555-5555-4555-8555-555555555555"
VARIABLES = "azurefactory/factories/acme-ai/scalesets/001/projects/project007/variables.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Factory API and all network calls are forbidden in input resolution")
    monkeypatch.setattr(socket, "create_connection", reject)


def register(provider="gha"):
    values = {"admin_aifactoryPrefixRG": "acme-", "admin_location": "swedencentral",
              "admin_locationSuffix": "sdc", "tenantId": TENANT, "dev_sub_id": SUB,
              "admin_aifactorySuffixRG": "-001", "project_number_000": "007"}
    return {
        "schema_version": 2, "generation": "new", "bindings": {},
        "factories": [{
            "id": FACTORY, "key": "acme-ai", "kind": "ai", "prefix": "acme-",
            "region": "swedencentral", "region_short_name": "sdc",
            "default_orchestrator": provider, "aifactory_version": "main", "version_ref": "main",
            "status": "draft", "scale_sets": [{
                "id": SCALE, "environment": "dev", "suffix": "001", "tenant_id": TENANT,
                "subscription_id": SUB, "orchestrator": provider, "status": "draft",
                "owned_resource_ids": [], "network": {"vnet_cidr": "10.140.0.0/16", "max_projects": 7}}],
            "projects": [{"id": PROJECT, "key": "project-007-001", "number": "007",
                          "display_name": "Example", "status": "draft", "storage_suffix": "001",
                          "placements": [{"environment": "dev", "scale_set_id": SCALE}]}]}],
        "configurations": {FACTORY: {"factory": {}, "scale_sets": {SCALE: {}},
                                     "projects": {PROJECT: {}},
                                     "variables": {PROJECT: {"dev": values, "stage_prod": {}}}}}}


def request(scenario=3, provider="gha"):
    result = {"schema": 1, "scenario": scenario, "provider": provider,
              "factory": "acme-ai", "environment": "all" if scenario == 6 else "dev",
              "source_ref": "refs/heads/main", "source_commit": "a" * 40}
    if scenario != 6:
        result["scale_set"] = "001"
    if scenario in (1, 3, 4):
        result["project"] = "007"
    return result


def save(root, document):
    path = root / "azurefactory" / "register.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    values = root / VARIABLES
    values.parent.mkdir(parents=True, exist_ok=True)
    values.write_text(json.dumps(document["configurations"][FACTORY]["variables"][PROJECT]), encoding="utf-8")


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
def test_six_scenarios_share_resolver_without_api(tmp_path, scenario, provider):
    save(tmp_path, register(provider))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    resolved = inputs.resolve_request(tmp_path, request(scenario, provider))
    assert resolved["request"]["scenario"] == scenario
    assert resolved["factory"]["id"] == FACTORY
    assert [scale["id"] for scale in resolved["scales"]] == [SCALE]
    assert resolved["source"] == {"ref": "refs/heads/main", "commit": "a" * 40}
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_zip_and_paths_have_identical_canonical_content(tmp_path):
    save(tmp_path, register())
    with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
        for path in (tmp_path / "azurefactory").rglob("*.json"):
            archive.write(path, path.relative_to(tmp_path).as_posix())
    direct = inputs.resolve_request(tmp_path, request() | {"variables": VARIABLES})
    bundled = inputs.resolve_request(tmp_path, request() | {"bundle": "input.zip", "variables": VARIABLES})
    for key in ("document", "factory", "scales", "projects", "configuration", "variables", "binding", "source"):
        assert direct[key] == bundled[key]
    assert not (tmp_path / ".extracted").exists()


@pytest.mark.parametrize("field,value", [
    ("scenario", True), ("scenario", 7), ("provider", "other"), ("factory", "../acme-ai"),
    ("environment", "all"), ("environment", "test"), ("scale_set", 1), ("scale_set", "01"),
    ("scale_set", "002"), ("project", "7"), ("project", "008"),
    ("source_commit", "main"), ("source_ref", "refs/heads/../main"),
    ("azurefactory_root", "../azurefactory"), ("variables", "C:\\outside.json"),
    ("variables", "../outside.json"), ("unknown", "ignored"),
    ("include_keyvault_and_resource_group", False),
])
def test_invalid_or_inapplicable_inputs_fail(tmp_path, field, value):
    save(tmp_path, register())
    with pytest.raises(inputs.InputError):
        inputs.resolve_request(tmp_path, request() | {field: value})


def test_duplicate_json_keys_are_rejected(tmp_path):
    save(tmp_path, register())
    path = tmp_path / "azurefactory" / "register.json"
    path.write_text('{"schema_version":2,"schema_version":2}', encoding="utf-8")
    with pytest.raises(inputs.InputError, match="duplicate"):
        inputs.resolve_request(tmp_path, request())


@pytest.mark.parametrize("mutation", [
    lambda d: d["factories"].append(copy.deepcopy(d["factories"][0])),
    lambda d: d["factories"][0]["scale_sets"].append(copy.deepcopy(d["factories"][0]["scale_sets"][0])),
    lambda d: d["factories"][0]["projects"][0]["placements"][0].update(environment="prod"),
    lambda d: d["configurations"][FACTORY]["variables"][PROJECT]["dev"].update(tenantId=SUB),
    lambda d: d["configurations"][FACTORY]["variables"][PROJECT]["dev"].update(project_number_000="001"),
    lambda d: d["configurations"][FACTORY]["factory"].update(client_secret="never-print-this"),
    lambda d: d["configurations"][FACTORY]["variables"][PROJECT]["dev"].update(extra='{"api_key":"never-print-this"}'),
])
def test_conflicting_register_and_credentials_fail(tmp_path, mutation):
    document = register()
    mutation(document)
    save(tmp_path, document)
    with pytest.raises(inputs.InputError) as error:
        inputs.resolve_request(tmp_path, request())
    assert "never-print-this" not in str(error.value)


def test_variables_cannot_silently_override_canonical_register(tmp_path):
    save(tmp_path, register())
    path = tmp_path / VARIABLES
    changed = json.loads(path.read_text())
    changed["dev"]["enableAzureOpenAI"] = True
    path.write_text(json.dumps(changed))
    for raw in (request(), request() | {"variables": VARIABLES}):
        with pytest.raises(inputs.InputError, match="projection"):
            inputs.resolve_request(tmp_path, raw)


def test_canonical_secret_id_alias_keeps_existing_api_configuration_compatible(tmp_path):
    document = register()
    values = document["configurations"][FACTORY]["variables"][PROJECT]["dev"]
    values["adminPasswordVMSecretId"] = "https://platform-vault.vault.azure.net/secrets/vm-password"
    save(tmp_path, document)
    assert inputs.resolve_request(tmp_path, request())["variables"][PROJECT]["dev"] == values
    value = {"reference": {
        "keyVault": {"id": f"/subscriptions/{SUB}/resourceGroups/platform/providers/Microsoft.KeyVault/vaults/platform-vault"},
        "secretName": "vm-password"}}
    values["adminPasswordVM"] = value
    save(tmp_path, document)
    with pytest.raises(inputs.InputError, match="canonical-secret-id"):
        inputs.resolve_request(tmp_path, request())
    value["reference"]["value"] = "not-allowed-plaintext"
    save(tmp_path, document)
    with pytest.raises(inputs.InputError) as error:
        inputs.resolve_request(tmp_path, request())
    assert "not-allowed-plaintext" not in str(error.value)


@pytest.mark.parametrize("entry", ["../escape.json", "/absolute.json", "C:/escape.json",
                                    "azurefactory\\register.json", "azurefactory/../register.json",
                                    "azurefactory/NUL.json", "azurefactory/hidden.json:stream"])
def test_zip_unsafe_paths_rejected_before_use(tmp_path, entry):
    with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
        archive.writestr("azurefactory/register.json", json.dumps(register()))
        archive.writestr(entry, "{}")
    with pytest.raises(inputs.InputError):
        inputs.resolve_request(tmp_path, request() | {"bundle": "input.zip"})


def test_zip_link_and_ambiguous_root_rejected(tmp_path):
    for link in (False, True):
        with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
            archive.writestr("azurefactory/register.json", json.dumps(register()))
            if link:
                info = zipfile.ZipInfo("azurefactory/escape.json")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "../../escape")
            else:
                archive.writestr("other/azurefactory/register.json", json.dumps(register()))
        with pytest.raises(inputs.InputError):
            inputs.resolve_request(tmp_path, request() | {"bundle": "input.zip"})


def test_zip_limits_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(inputs, "MAX_ARCHIVE_BYTES", 100)
    with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
        archive.writestr("azurefactory/register.json", json.dumps(register()))
    with pytest.raises(inputs.InputError, match="size"):
        inputs.resolve_request(tmp_path, request() | {"bundle": "input.zip"})


def test_deletion_options_are_exact_booleans(tmp_path):
    save(tmp_path, register())
    resolved = inputs.resolve_request(tmp_path, request(4) | {
        "include_project_subnets": True, "include_keyvault_and_resource_group": False})
    assert resolved["request"]["include_keyvault_and_resource_group"] is False
    with pytest.raises(inputs.InputError):
        inputs.resolve_request(tmp_path, request(4) | {"include_project_subnets": "false"})


def test_same_number_in_another_environment_never_selected(tmp_path):
    document = register()
    extra = copy.deepcopy(document["factories"][0]["scale_sets"][0])
    extra.update(id="66666666-6666-4666-8666-666666666666", environment="prod")
    document["factories"][0]["scale_sets"].append(extra)
    document["configurations"][FACTORY]["scale_sets"][extra["id"]] = {}
    save(tmp_path, document)
    assert [s["environment"] for s in inputs.resolve_request(tmp_path, request(5))["scales"]] == ["dev"]
    assert len(inputs.resolve_request(tmp_path, request(6))["scales"]) == 2


def test_factory_projection_must_not_disagree_with_register(tmp_path):
    document = register()
    save(tmp_path, document)
    path = tmp_path / "azurefactory" / "factories" / "acme-ai" / "factory.json"
    path.write_text(json.dumps({**document["factories"][0], "generation": "new",
                                "settings": {}, "prefix": "wrong-"}))
    with pytest.raises(inputs.InputError, match="projection"):
        inputs.resolve_request(tmp_path, request())


def test_projection_generation_drift_is_evidence_not_a_gate(tmp_path):
    document = register()
    save(tmp_path, document)
    path = tmp_path / "azurefactory" / "factories" / "acme-ai" / "factory.json"
    path.write_text(json.dumps({**document["factories"][0], "generation": "older", "settings": {}}))
    resolved = inputs.resolve_request(tmp_path, request())
    assert resolved["warnings"] == ["projection-generation-drift:factories/acme-ai/factory.json"]


def test_secret_named_variable_does_not_get_printed_by_cli(tmp_path, capsys):
    document = register()
    document["configurations"][FACTORY]["factory"]["password"] = "value-not-for-logs"
    save(tmp_path, document)
    (tmp_path / "request.json").write_text(json.dumps(request()))
    assert inputs.main(["--repository-root", str(tmp_path), "--request", "request.json"]) == 2
    assert "value-not-for-logs" not in capsys.readouterr().err


@pytest.mark.parametrize("binding", [
    {"provider": "ado"}, {"orchestrator": "ado"}, {"factory_id": SUB},
    {"tenant_id": SUB}, {"subscription_id": TENANT}, {"environment": "prod"},
])
def test_operational_binding_cannot_conflict_with_selected_identity(tmp_path, binding):
    save(tmp_path, register())
    (tmp_path / "binding.json").write_text(json.dumps(binding))
    with pytest.raises(inputs.InputError, match="binding"):
        inputs.resolve_request(tmp_path, request() | {"provider_binding": "binding.json"})


def test_zip_case_variant_second_register_is_ambiguous(tmp_path):
    with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
        archive.writestr("azurefactory/register.json", json.dumps(register()))
        archive.writestr("other/azurefactory/REGISTER.json", json.dumps(register()))
    with pytest.raises(inputs.InputError):
        inputs.resolve_request(tmp_path, request() | {"bundle": "input.zip"})


@pytest.mark.parametrize("name", ["githubToken", "AZURE_STORAGE_KEY", "accountKey", "clientAssertion"])
def test_common_credential_spellings_are_rejected(tmp_path, name):
    document = register()
    document["configurations"][FACTORY]["variables"][PROJECT]["dev"][name] = "not-for-artifacts"
    save(tmp_path, document)
    with pytest.raises(inputs.InputError, match="credential"):
        inputs.resolve_request(tmp_path, request())


@pytest.mark.parametrize("value", [
    "ghp_" + "a" * 36, "github_pat_" + "a" * 40,
    "eyJ" + "a" * 24 + "." + "b" * 24 + "." + "c" * 24,
])
def test_recognizable_credential_values_are_not_configuration(value):
    with pytest.raises(inputs.InputError, match="credential"):
        inputs.public_configuration({"otherwise_ordinary_field": value})


def test_secret_reference_exception_cannot_hide_a_credential():
    with pytest.raises(inputs.InputError, match="reference"):
        inputs.public_configuration({"secret_uri": "not-a-vault-reference"})
    inputs.public_configuration({"secret_uri": "https://example.vault.azure.net/secrets/example"})
    inputs.public_configuration({"credential_environment": "DEPLOYMENT_CREDENTIAL"})


def test_arm_keyvault_reference_is_configuration_not_plaintext():
    reference = {"reference": {
        "keyVault": {"id": f"/subscriptions/{SUB}/resourceGroups/platform/providers/Microsoft.KeyVault/vaults/platform-kv"},
        "secretName": "deployment-secret", "secretVersion": "a" * 32}}
    inputs.public_configuration({"secure_parameters": {"parameter": reference}})
    invalid = copy.deepcopy(reference)
    invalid["reference"]["secretName"] = "value with spaces and arbitrary content"
    with pytest.raises(inputs.InputError, match="reference"):
        inputs.public_configuration(invalid)
    invalid = copy.deepcopy(reference)
    invalid["reference"]["client_secret"] = "not-for-artifacts"
    with pytest.raises(inputs.InputError):
        inputs.public_configuration(invalid)
