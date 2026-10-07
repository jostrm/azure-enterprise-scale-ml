"""Exact, read-only AML attachment discovery; failures must never mean absent."""

import importlib.util
from pathlib import Path
import sys

import pytest


BICEP = Path(__file__).resolve().parents[3] / "aifactory" / "bicep"
sys.path.insert(0, str(BICEP))
from personas.cli import AzureCLIError


@pytest.fixture
def discovery():
    path = BICEP / "scripts" / "discover-aml-aks-attachment.py"
    spec = importlib.util.spec_from_file_location("aml_aks_attachment_discovery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUB = "00000000-0000-0000-0000-000000000003"
RG = "spider-esml-project003-sdc-dev-001-rg"
COMMON = "spider-esml-common-sdc-dev-001-rg"
SCOPE = f"/subscriptions/{SUB}/resourceGroups/{RG}"
AKS = f"{SCOPE}/providers/Microsoft.ContainerService/managedClusters/aks003-sdc-dev"
AML = f"{SCOPE}/providers/Microsoft.MachineLearningServices/workspaces/aml-003-sdc-dev-bltsc-001"
COMPUTE = f"{AML}/computes/aks003-sdc-dev"
NAMING = f"{SCOPE}/providers/Microsoft.Resources/deployments/01-naming-{RG}"


def compute():
    return {
        "id": COMPUTE,
        "type": "Microsoft.MachineLearningServices/workspaces/computes",
        "properties": {
            "computeType": "AKS", "provisioningState": "Succeeded", "resourceId": AKS,
        },
    }


def naming():
    return {
        "id": NAMING,
        "properties": {
            "provisioningState": "Succeeded",
            "parameters": {
                key: {"value": value} for key, value in {
                    "subscriptionIdDevTestProd": SUB, "commonResourceGroupName": COMMON,
                    "projectNumber": "003", "locationSuffix": "sdc", "env": "dev",
                    "resourceSuffix": "-001",
                }.items()
            },
            "outputs": {"uniqueInAIFenv": {"value": "bltsc"}},
        },
    }


def settings(**overrides):
    return {
        "subscription": SUB, "resource_group": RG, "common_resource_group": COMMON,
        "project_number": "003", "location_suffix": "sdc", "environment": "dev",
        "resource_suffix": "-001", "add_workspace": False,
        "salt": "ab-cd-ef123", "random_value": "0123456789",
        **overrides,
    }


class Azure:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        assert args[:3] == ("rest", "--method", "get")
        assert "--subscription" in args
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_healthy_exact_attachment_skips_without_any_put(discovery):
    azure = Azure(naming(), compute())
    assert discovery.discover_attachment(azure, **settings()) is True
    assert len(azure.calls) == 2
    assert azure.calls[0][4] == f"https://management.azure.com{NAMING}?api-version=2022-09-01"
    assert azure.calls[1][4] == f"https://management.azure.com{COMPUTE}?api-version=2025-07-01-preview"


@pytest.mark.parametrize("parent_exists", [False, True])
def test_missing_attachment_allows_create_independently_of_cluster_or_workspace(discovery, parent_exists):
    # ARM returns 404 both for a missing workspace and a missing compute.
    code = "ResourceNotFound" if parent_exists else "ParentResourceNotFound"
    azure = Azure(naming(), AzureCLIError("not found", status_code=404, error_code=code))
    assert discovery.discover_attachment(azure, **settings()) is False


@pytest.mark.parametrize("error", [
    AzureCLIError("unauthorized", status_code=401),
    AzureCLIError("forbidden", status_code=403),
    AzureCLIError("server", status_code=500),
    AzureCLIError("ResourceNotFound without HTTP status", error_code="ResourceNotFound"),
    AzureCLIError("404 appears in arbitrary error text"),
    ValueError("invalid json"), TimeoutError("timeout"),
])
def test_only_typed_404_means_attachment_absent(discovery, error):
    with pytest.raises(type(error)):
        discovery.discover_attachment(Azure(naming(), error), **settings())


@pytest.mark.parametrize("field,value", [
    ("id", COMPUTE.replace("/workspaces/aml-", "/workspaces/other-")),
    ("id", COMPUTE.replace("/computes/aks003-", "/computes/aks004-")),
    ("type", "Microsoft.MachineLearningServices/workspaces"),
    ("computeType", "Kubernetes"), ("computeType", None),
    ("resourceId", AKS.replace("aks003-", "aks004-")),
    ("resourceId", AKS.replace(SUB, "00000000-0000-0000-0000-000000000004")),
    ("resourceId", AKS.replace(RG, "another-rg")),
    ("resourceId", None), ("provisioningState", "Failed"),
    ("provisioningState", "Creating"), ("provisioningState", "Updating"),
    ("provisioningState", "Deleting"), ("provisioningState", None),
])
def test_mismatched_or_unhealthy_attachment_fails_closed(discovery, field, value):
    response = compute()
    (response if field in ("id", "type") else response["properties"])[field] = value
    with pytest.raises(ValueError):
        discovery.discover_attachment(Azure(naming(), response), **settings())


@pytest.mark.parametrize("response", [None, [], {}, {"properties": None}, {"id": COMPUTE, "properties": []}])
def test_malformed_success_response_fails_closed(discovery, response):
    with pytest.raises(ValueError):
        discovery.discover_attachment(Azure(naming(), response), **settings())


def test_arm_resource_ids_are_case_insensitive(discovery):
    response = compute()
    response["id"] = COMPUTE.upper()
    response["properties"]["resourceId"] = AKS.upper()
    assert discovery.discover_attachment(Azure(naming(), response), **settings()) is True


@pytest.mark.parametrize("field", ["subscriptionIdDevTestProd", "commonResourceGroupName", "projectNumber", "locationSuffix", "env", "resourceSuffix"])
def test_stale_naming_deployment_cannot_select_wrong_workspace(discovery, field):
    response = naming()
    response["properties"]["parameters"][field]["value"] = "different"
    azure = Azure(response)
    with pytest.raises(ValueError):
        discovery.discover_attachment(azure, **settings())
    assert len(azure.calls) == 1


@pytest.mark.parametrize("response", [
    {}, None, {"id": NAMING, "properties": {"provisioningState": "Failed"}},
    AzureCLIError("missing naming is not missing compute", status_code=404),
])
def test_unusable_naming_metadata_never_means_compute_absent(discovery, response):
    with pytest.raises((ValueError, AzureCLIError)):
        discovery.discover_attachment(Azure(response), **settings())


@pytest.mark.parametrize("overrides,expected_name", [
    ({}, "aml-003-sdc-dev-bltsc-001"),
    ({"add_workspace": True}, "aml-003-sdc-dev-bltscab-001"),
    ({"add_workspace": True, "salt": "", "random_value": "_-CD1234567"}, "aml-003-sdc-dev-bltsccd-001"),
])
def test_random_workspace_names_follow_bicep_not_fuzzy_first_match(discovery, overrides, expected_name):
    azure = Azure(naming(), AzureCLIError("absent", status_code=404))
    assert discovery.discover_attachment(azure, **settings(**overrides)) is False
    assert f"/workspaces/{expected_name}/computes/aks003-sdc-dev?" in azure.calls[-1][4]


def test_cli_emits_only_boolean_after_success_and_no_fallback_on_error(discovery, monkeypatch, capsys):
    args = [
        "--subscription", SUB, "--resource-group", RG, "--common-resource-group", COMMON,
        "--project-number", "003", "--location-suffix", "sdc", "--environment", "dev",
        "--resource-suffix=-001", "--add-workspace=false", "--salt=ab-cd-ef123",
        "--random-value=0123456789",
    ]
    monkeypatch.setattr(discovery, "azure_cli", Azure(naming(), compute()))
    assert discovery.main(args) == 0
    assert capsys.readouterr().out == "true\n"
    monkeypatch.setattr(discovery, "azure_cli", Azure(naming(), AzureCLIError("forbidden", status_code=403)))
    assert discovery.main(args) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "forbidden" in output.err
