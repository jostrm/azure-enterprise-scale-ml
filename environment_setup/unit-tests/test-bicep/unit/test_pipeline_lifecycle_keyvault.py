"""ARM Key Vault references are metadata, never fetched secret values."""

import copy
import importlib
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import (
    fl, ROOT, SUB, GROUP, scoped_manifest, PlanCloud, simple_plan_closure, seal, no_real_services,
)

sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))

VAULT = f"/subscriptions/{SUB}/resourceGroups/platform/providers/Microsoft.KeyVault/vaults/platform-vault"
REFERENCE = {"reference": {"keyVault": {"id": VAULT}, "secretName": "vm-password", "secretVersion": "e" * 32}}


def helper():
    return importlib.import_module("pipeline_lifecycle_keyvault")


def prepared_reference():
    document, templates = scoped_manifest()
    document["deployment"]["parameter_transport"] = "arm-keyvault-reference-v1"
    for step in document["deployment"]["steps"]:
        templates[step["template"]]["parameters"]["adminPasswordVM"] = {"type": "secureString"}
        step["parameters"]["adminPasswordVM"] = copy.deepcopy(REFERENCE)
        step["template_hash"] = fl.digest(templates[step["template"]])
    cloud = Mock()
    cloud.compile_template.side_effect = lambda root, name: copy.deepcopy(templates[name])
    return document, cloud


def test_reference_is_versioned_metadata_without_mutation():
    original = copy.deepcopy(REFERENCE)
    assert helper().validate_reference(REFERENCE) == original
    assert REFERENCE == original


@pytest.mark.parametrize("change", ["malformed-version", "payload", "wrong-vault", "expression"])
def test_reference_rejects_malformed_versions_and_payloads(change):
    value = copy.deepcopy(REFERENCE)
    if change == "malformed-version":
        value["reference"]["secretVersion"] = "not-a-version"
    elif change == "payload":
        value["reference"]["value"] = "must-never-be-stored"
    elif change == "wrong-vault":
        value["reference"]["keyVault"]["id"] = "https://example.com/secret"
    else:
        value["reference"]["secretName"] = "[parameters('secret')]"
    with pytest.raises(ValueError):
        helper().validate_reference(value)


def test_secure_parameter_resolver_accepts_reference_not_literal():
    from pipeline_lifecycle_parameters import parameters
    from .test_pipeline_lifecycle_parameters import target
    template = {"parameters": {"adminPasswordVM": {"type": "secureString"}}}
    assert parameters(template, {"adminPasswordVM": REFERENCE}, target()) == {"adminPasswordVM": REFERENCE}
    with pytest.raises(ValueError, match="secure-parameter-transport"):
        parameters(template, {"adminPasswordVM": "literal-secret"}, target())


def test_existing_secret_id_input_contract_resolves_without_secret_reads():
    from pipeline_lifecycle_parameters import parameters
    from pipeline_inputs import public_configuration
    from .test_pipeline_lifecycle_parameters import target
    values = {"adminPasswordVMSecretId": "https://platform-vault.vault.azure.net/secrets/vm-password/" + "e" * 32,
              "inputKeyvault": "platform-vault", "inputKeyvaultResourcegroup": "platform",
              "inputKeyvaultSubscription": SUB}
    public_configuration(values)
    template = {"parameters": {"adminPasswordVM": {"type": "secureString"}}}
    assert parameters(template, values, target())["adminPasswordVM"] == REFERENCE


def test_unversioned_seed_reference_uses_arm_authorization_without_reading_secret():
    from pipeline_lifecycle_parameters import parameters
    from .test_pipeline_lifecycle_parameters import target
    expected = copy.deepcopy(REFERENCE)
    expected["reference"].pop("secretVersion")
    assert helper().validate_reference(expected) == expected
    values = {"adminPasswordVMSecretId": "https://platform-vault.vault.azure.net/secrets/vm-password",
              "inputKeyvault": "platform-vault", "inputKeyvaultResourcegroup": "platform",
              "inputKeyvaultSubscription": SUB}
    template = {"parameters": {"adminPasswordVM": {"type": "secureString"}}}
    assert parameters(template, values, target())["adminPasswordVM"] == expected


def test_sensitive_parameter_key_can_store_only_validated_reference():
    from pipeline_lifecycle_adapters import no_secret_material
    no_secret_material({"adminPassword": REFERENCE})
    with pytest.raises(ValueError):
        no_secret_material({"adminPassword": {"reference": {"value": "literal-secret"}}})


def test_native_single_step_emits_arm_reference_not_value():
    document, cloud = prepared_reference()
    result = fl.compiled_plan_step(cloud, document, document["deployment"]["steps"][0], ROOT)
    assert result["properties"]["parameters"]["adminPasswordVM"] == REFERENCE


def test_native_combined_payload_lifts_references_out_of_secure_objects():
    document, cloud = prepared_reference()
    before = copy.deepcopy(document)
    result = fl.combined_plan_payload(cloud, document, ROOT)
    assert document == before
    properties = result["properties"]
    referenced = {key for key, value in properties["parameters"].items() if "reference" in value}
    assert len(referenced) == len(document["deployment"]["steps"])
    for index, nested in enumerate(properties["template"]["resources"]):
        key = f"aif_kv_{index}_adminPasswordVM"
        assert properties["parameters"][key] == REFERENCE
        assert properties["template"]["parameters"][key]["type"] == "secureString"
        assert nested["properties"]["parameters"]["adminPasswordVM"] == {"value": f"[parameters('{key}')]"}
        assert "adminPasswordVM" not in properties["parameters"][f"step_{index}"]["value"]


def test_reference_cannot_be_substituted_for_nonsecure_parameter():
    payload = {"properties": {"template": {"parameters": {"name": {"type": "string"}}},
                              "parameters": {"name": {"value": REFERENCE}}}}
    with pytest.raises(ValueError, match="secure"):
        helper().encode_step_payload(payload)


def test_legacy_native_payload_is_unchanged_without_opt_in():
    document, cloud = prepared_reference()
    document["deployment"].pop("parameter_transport")
    result = fl.compiled_plan_step(cloud, document, document["deployment"]["steps"][0], ROOT)
    assert result["properties"]["parameters"]["adminPasswordVM"] == {"value": REFERENCE}


def test_real_native_worker_emits_references_without_materializing_secrets(monkeypatch):
    document, compiler = prepared_reference()
    templates = {step["template"]: compiler.compile_template(ROOT, step["template"])
                 for step in document["deployment"]["steps"]}
    cloud = PlanCloud(document, templates)
    document["config"] = {}
    document["deployment"]["configuration_hash"] = fl.digest({})
    document["locks"]["common_dependencies"] = []
    cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    result = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                     ROOT, document["run_id"], document["manifest_hash"],
                                     cloud=cloud, sleep=Mock())
    assert result["status"] == "succeeded", result
    assert len(cloud.arm_writes) == 1
    body = cloud.arm_writes[0][1]["properties"]
    assert sum(value == REFERENCE for value in body["parameters"].values()) == 3
    assert all("adminPasswordVM" not in value.get("value", {}) for key, value in body["parameters"].items()
               if key.startswith("step_"))
