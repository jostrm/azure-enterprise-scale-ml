import copy
import json
import stat
import subprocess
from datetime import datetime
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from src import api, operations, project_verification as verification, scale_set_verification as shared, wizard
from src.factory_scope import current_factory_scope


SUB = "11111111-1111-4111-8111-111111111111"
OTHER_SUB = "33333333-3333-4333-8333-333333333333"
TENANT = "22222222-2222-4222-8222-222222222222"
OTHER_TENANT = "44444444-4444-4444-8444-444444444444"
TOKEN = "private-project-token.DO_NOT_SERIALIZE"
NAME = "demo-esml-project017-sdc-dev-007"
RG_ID = f"/subscriptions/{SUB}/resourceGroups/{NAME}"
ENDPOINT = "/api/v1/projects/verify-resource-groups"


def response(request, *, resource_id=None, status=200, body=None, content_type="application/json", url=None):
    headers = Message()
    headers["Content-Type"] = content_type
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.getcode.return_value = status
    result.headers = headers
    resource_id = resource_id or request.full_url.removeprefix(shared.ARM_ORIGIN).split("?")[0]
    result.read.return_value = json.dumps({"id": resource_id}).encode() if body is None else body
    result.geturl.return_value = url or request.full_url
    return result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "factory"
    snapshots = root / "config-wizard" / "project-017"
    snapshots.mkdir(parents=True)
    saved = {
        "project_number_000": "017", "orchestrator": "ado",
        "admin_aifactoryPrefixRG": "demo-", "admin_aifactorySuffixRG": "-007",
        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "dev_sub_id": SUB, "test_sub_id": SUB, "prod_sub_id": SUB, "tenantId": TENANT,
    }
    current_path = root / "config-wizard" / "factory_state.json"
    current_path.write_text(json.dumps(saved))
    snapshot = snapshots / "project_state.json"
    snapshot.write_text(json.dumps(saved))
    scope = current_factory_scope(root)
    group = {"id": RG_ID, "name": NAME, "subscriptionId": SUB, "location": "swedencentral"}
    env = {"environment": "dev", "status": "active", "region": "swedencentral",
           "regions": ["swedencentral"], "subscription_id": SUB, "resource_group": NAME,
           "resource_groups": [NAME],
           "resource_group_refs": [{"id": RG_ID, "name": NAME, "subscription_id": SUB, "tenant_id": TENANT}]}
    overview = {
        "factory": {"folder": str(root), "prefix_rg": "demo-", "suffix_rg": "-007",
                    "monitoring_regions": scope["monitoring_regions"], "subscription_ids": [SUB]},
        "projects": [{"project_number": "017", "environments": [env]}],
        "common_resource_groups": [{
            "id": RG_ID.replace("project017", "common"), "name": NAME.replace("project017", "common"),
            "subscriptionId": SUB, "location": "swedencentral",
        }],
        "resource_inventory": {"resource_groups": [group]},
        "source": "cached",
    }
    service = Mock()
    service.overview.return_value = overview
    runner = Mock(return_value=subprocess.CompletedProcess(
        [], 0, json.dumps({"accessToken": TOKEN, "subscription": SUB, "tenant": TENANT}), "",
    ))
    opener = Mock()
    opener.open.side_effect = lambda request, **kwargs: response(request)
    monkeypatch.setattr(operations, "resolve_azure_cli", lambda: "az.exe")
    monkeypatch.setattr(shared.subprocess, "run", runner)
    monkeypatch.setattr(shared, "build_opener", Mock(return_value=opener))
    monkeypatch.setattr(operations, "OperationsService", Mock(return_value=service))
    return SimpleNamespace(
        root=root, snapshot=snapshot, current_path=current_path, saved=saved, env=env, group=group,
        overview=overview, service=service, runner=runner, opener=opener,
        body={"aifactory_folder": str(root), "project_number": "017", "path": str(snapshot)},
    )


def verify(setup):
    return verification.verify_resource_groups(**setup.body)


def assert_not_verified(result):
    assert not (result["checks"] and all(check["verified"] for check in result["checks"]))
    assert TOKEN not in json.dumps(result)


def test_exact_project017_scoped_fresh_arm200_is_read_only(setup, caplog):
    before = setup.snapshot.read_bytes(), setup.current_path.read_bytes()
    result = verify(setup)
    assert result["project_number"] == "017"
    assert datetime.fromisoformat(result["checked_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    assert result["checks"][0]["verified"] is True
    assert result["checks"][0]["resource_id"] == RG_ID
    assert result["checks"][0]["http_status"] == 200
    setup.service.overview.assert_called_once_with(str(setup.root), include_azure=True, force_refresh=False)
    request = setup.opener.open.call_args.args[0]
    assert request.full_url == shared.ARM_ORIGIN + RG_ID + "?api-version=2021-04-01"
    assert request.method == "GET"
    assert request.get_header("Authorization") == "Bearer " + TOKEN
    command = setup.runner.call_args.args[0]
    assert command[command.index("--subscription") + 1] == SUB
    assert command[command.index("--resource") + 1] == shared.ARM_ORIGIN + "/"
    assert "set" not in command and "login" not in command
    assert before == (setup.snapshot.read_bytes(), setup.current_path.read_bytes())
    assert TOKEN not in json.dumps(result) and TOKEN not in caplog.text
    verify(setup)
    assert setup.runner.call_count == 2 and setup.opener.open.call_count == 2


@pytest.mark.parametrize("number", ["17", "0017", "017"])
def test_numeric_identity_ignores_leading_zeroes(setup, number):
    setup.body["project_number"] = number
    setup.snapshot.write_text(json.dumps({**setup.saved, "project_number_000": "17"}))
    setup.overview["projects"][0]["project_number"] = "0017"
    assert verify(setup)["checks"][0]["verified"]


@pytest.mark.parametrize("status", [401, 403, 404, 204, 202, 301, 302, 307, 500])
def test_only_real200_can_verify_and_status_is_preserved(setup, status):
    setup.opener.open.side_effect = lambda request, **kwargs: response(request, status=status)
    result = verify(setup)
    assert_not_verified(result)
    assert result["checks"][0]["http_status"] == status


@pytest.mark.parametrize("status", [403, 404, 302])
def test_http_errors_are_sanitized_and_do_not_redirect(setup, status):
    setup.opener.open.side_effect = HTTPError(shared.ARM_ORIGIN, status, TOKEN, {}, None)
    result = verify(setup)
    assert_not_verified(result)
    assert result["checks"][0]["http_status"] == status
    assert setup.opener.open.call_count == 1


@pytest.mark.parametrize("kwargs", [
    {"resource_id": RG_ID.replace("project017", "project018")},
    {"resource_id": RG_ID + "/providers/Microsoft.Compute/virtualMachines/vm"},
    {"content_type": "text/html"},
    {"url": "https://portal.azure.com"},
    {"body": b"not-json"},
    {"body": b"[]"},
])
def test_wrong200_is_not_access_evidence(setup, kwargs):
    setup.opener.open.side_effect = lambda request, **unused: response(request, **kwargs)
    result = verify(setup)
    assert_not_verified(result)
    assert result["checks"][0]["http_status"] == 200


@pytest.mark.parametrize("document,code", [
    ({"accessToken": TOKEN, "subscription": OTHER_SUB, "tenant": TENANT}, 0),
    ({"accessToken": TOKEN, "subscription": SUB, "tenant": OTHER_TENANT}, 0),
    ({"accessToken": "\r\n" + TOKEN, "subscription": SUB, "tenant": TENANT}, 0),
    ({"accessToken": TOKEN}, 0),
    ({}, 1),
])
def test_invalid_credentials_never_send_arm_request(setup, document, code):
    setup.runner.return_value = subprocess.CompletedProcess([], code, json.dumps(document), TOKEN)
    result = verify(setup)
    assert_not_verified(result)
    assert result["checks"][0]["http_status"] is None
    setup.opener.open.assert_not_called()


@pytest.mark.parametrize("error", [URLError(TOKEN), TimeoutError(TOKEN)])
def test_transport_errors_do_not_expose_secrets(setup, error):
    setup.opener.open.side_effect = error
    result = verify(setup)
    assert_not_verified(result)
    assert result["checks"][0]["http_status"] is None


def test_no_observed_group_does_not_check_common_or_configured_names(setup):
    setup.env.update(resource_group=None, resource_groups=[], resource_group_refs=[],
                     status="not_deployed", isDeployed=True)
    result = verify(setup)
    assert result["checks"] == []
    setup.runner.assert_not_called()
    setup.opener.open.assert_not_called()


@pytest.mark.parametrize("replacement", ["common", "project018", "project017-common"])
def test_project_never_checks_common_or_other_project_group(setup, replacement):
    ref = setup.env["resource_group_refs"][0]
    ref["id"] = RG_ID.replace("project017", replacement)
    ref["name"] = NAME.replace("project017", replacement)
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("id", "https://management.azure.com" + RG_ID),
    ("id", RG_ID + "/providers/Microsoft.Storage/storageAccounts/test"),
    ("id", RG_ID + "?query=test"),
    ("id", RG_ID.replace(SUB, "bad-sub")),
    ("name", "different-name"),
    ("subscription_id", OTHER_SUB),
    ("tenant_id", OTHER_TENANT),
    ("tenant_id", "not-a-tenant"),
])
def test_invalid_observed_reference_never_queries(setup, field, value):
    setup.env["resource_group_refs"][0][field] = value
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


@pytest.mark.parametrize("old,new", [
    ("demo-", "foreign-"), ("-007", "-999"), ("-sdc-", "-eus2-"), ("-dev-", "-prod-"),
])
def test_same_project_number_other_factory_or_environment_is_isolated(setup, old, new):
    ref = setup.env["resource_group_refs"][0]
    ref.update(id=RG_ID.replace(old, new), name=NAME.replace(old, new))
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_group_location_must_match_current_region(setup):
    setup.group["location"] = "eastus2"
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_environment_region_fallback_and_ambiguous_regions(setup):
    setup.overview.pop("resource_inventory")
    assert verify(setup)["checks"][0]["verified"]
    setup.runner.reset_mock()
    setup.env["regions"].append("eastus2")
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_refs_preferred_over_incorrect_legacy_singular_subscription(setup):
    setup.env.update(resource_group="wrong", subscription_id=OTHER_SUB, resource_groups=["wrong", "other"])
    assert verify(setup)["checks"][0]["verified"]


def test_safe_single_group_legacy_fallback(setup):
    setup.env.pop("resource_group_refs")
    assert verify(setup)["checks"][0]["verified"]


def test_legacy_names_must_not_be_combined_with_one_subscription(setup):
    setup.env.pop("resource_group_refs")
    setup.env["resource_groups"].append(NAME.replace("esml", "genai"))
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_multiple_groups_environments_and_subscriptions_are_checked_once(setup):
    current = {**setup.saved, "test_sub_id": OTHER_SUB, "prod_sub_id": OTHER_SUB}
    setup.current_path.write_text(json.dumps(current))
    setup.snapshot.write_text(json.dumps(current))
    setup.overview["factory"]["subscription_ids"] = [SUB, OTHER_SUB]
    setup.env["resource_group_refs"].append(copy.deepcopy(setup.env["resource_group_refs"][0]))
    for env, sub in [("dev", SUB), ("stage", OTHER_SUB), ("prod", OTHER_SUB)]:
        name = NAME.replace("esml", "genai").replace("-dev-", f"-{env}-")
        ref = {"id": f"/subscriptions/{sub}/resourceGroups/{name}",
               "name": name, "subscription_id": sub, "tenant_id": TENANT}
        if env == "dev":
            setup.env["resource_group_refs"].append(ref)
        else:
            setup.overview["projects"][0]["environments"].append({
                "environment": env, "region": "swedencentral", "resource_group_refs": [ref],
            })
    setup.runner.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(
        [], 0, json.dumps({"accessToken": TOKEN,
                          "subscription": command[command.index("--subscription") + 1], "tenant": TENANT}), "",
    )
    result = verify(setup)
    assert len(result["checks"]) == 4
    assert all(check["verified"] for check in result["checks"])
    assert setup.runner.call_count == 2 and setup.opener.open.call_count == 4
    assert len({check["resource_id"].casefold() for check in result["checks"]}) == 4


def test_reference_cannot_move_a_dev_group_to_stage_subscription(setup):
    current = {**setup.saved, "test_sub_id": OTHER_SUB}
    setup.current_path.write_text(json.dumps(current))
    setup.snapshot.write_text(json.dumps(current))
    setup.overview["factory"]["subscription_ids"] = [SUB, OTHER_SUB]
    setup.env["resource_group_refs"][0].update(id=RG_ID.replace(SUB, OTHER_SUB), subscription_id=OTHER_SUB)
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_maximum_group_limit_is_all_or_nothing(setup):
    setup.env["resource_group_refs"] = [
        {"id": RG_ID.replace("esml", f"genai{i}"), "name": NAME.replace("esml", f"genai{i}"),
         "subscription_id": SUB} for i in range(13)
    ]
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


@pytest.mark.parametrize("value", ["018", "", None, 17, "x17"])
def test_wrong_raw_project_identity_is_rejected_before_inventory(setup, value):
    setup.snapshot.write_text(json.dumps({**setup.saved, "project_number_000": value}))
    with pytest.raises(verification.VerificationRequestError) as error:
        verify(setup)
    assert error.value.status_code == 409
    setup.service.overview.assert_not_called()
    setup.runner.assert_not_called()


def test_mismatched_path_is_rejected_before_inventory(setup):
    other = setup.snapshot.parent / "other.json"
    other.write_text(json.dumps(setup.saved))
    setup.body["path"] = str(other)
    with pytest.raises(verification.VerificationRequestError) as error:
        verify(setup)
    assert error.value.status_code == 409
    setup.service.overview.assert_not_called()


@pytest.mark.parametrize("owner", ["", "foreign"])
def test_legacy_requires_nonempty_matching_factory_owner(setup, monkeypatch, owner):
    legacy = setup.root / "legacy" / "project_017.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({**setup.saved, "_save_folder": str(setup.root / owner) if owner else ""}))
    setup.body["path"] = str(legacy)
    listing = Mock(return_value={"017": str(legacy)})
    monkeypatch.setattr(wizard, "_list_project_snapshots", listing)
    with pytest.raises(verification.VerificationRequestError) as error:
        verify(setup)
    assert error.value.status_code == 409
    listing.assert_called_once_with(str(setup.root), create_legacy_dir=False)
    setup.runner.assert_not_called()


def test_matching_owned_legacy_snapshot_can_verify(setup, monkeypatch):
    legacy = setup.root / "project_017.json"
    legacy.write_text(json.dumps({**setup.saved, "_save_folder": str(setup.root)}))
    setup.body["path"] = str(legacy)
    monkeypatch.setattr(wizard, "_list_project_snapshots", lambda *args, **kwargs: {"017": str(legacy)})
    assert verify(setup)["checks"][0]["verified"]


def test_project017_missing_fields_uses_same_current_source_as_listing(setup):
    setup.snapshot.write_text(json.dumps({"project_number_000": "017"}))
    listed = api.projects(api.FolderBody(aifactory_folder=str(setup.root)))["projects"][0]
    assert listed["deployment_scope"]["prefix_rg"] == "demo-"
    assert verify(setup)["checks"][0]["verified"]


def test_current_other_project_cannot_supply_missing_identity(setup):
    setup.snapshot.write_text(json.dumps({"project_number_000": "017"}))
    setup.current_path.write_text(json.dumps({**setup.saved, "project_number_000": "018"}))
    assert verify(setup)["checks"] == []
    setup.service.overview.assert_not_called()
    setup.runner.assert_not_called()


@pytest.mark.parametrize("number,expected", [("017", True), ("018", False)])
def test_root_variables_hydrate_only_the_saved_project(setup, number, expected):
    setup.current_path.unlink()
    setup.snapshot.write_text(json.dumps({"project_number_000": "017"}))
    values = {**setup.saved, "project_number_000": number}
    (setup.root / "variables.json").write_text(json.dumps({"dev": values, "stage_prod": values}))
    result = verify(setup)
    assert bool(result["checks"] and result["checks"][0]["verified"]) is expected
    if not expected:
        setup.service.overview.assert_not_called()
        setup.runner.assert_not_called()


def test_multi_region_environment_uses_actual_group_subscription_and_tenant(setup):
    setup.current_path.unlink()
    stage = {**setup.saved, "test_sub_id": OTHER_SUB, "prod_sub_id": OTHER_SUB,
             "tenantId": OTHER_TENANT, "admin_location": "eastus2", "admin_locationSuffix": "eus2"}
    dev = {**setup.saved, "test_sub_id": OTHER_SUB, "prod_sub_id": OTHER_SUB}
    setup.snapshot.write_text(json.dumps(dev))
    (setup.root / "variables.json").write_text(json.dumps({"dev": dev, "stage_prod": stage}))
    setup.overview["factory"].update(
        subscription_ids=[SUB, OTHER_SUB], monitoring_regions=["swedencentral", "eastus2"],
    )
    name = NAME.replace("-sdc-dev-", "-eus2-stage-")
    stage_id = f"/subscriptions/{OTHER_SUB}/resourceGroups/{name}"
    setup.overview["projects"][0]["environments"].append({
        "environment": "stage", "region": "eastus2",
        "resource_group_refs": [{"id": stage_id, "name": name,
                                "subscription_id": OTHER_SUB, "tenant_id": OTHER_TENANT}],
    })
    setup.runner.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(
        [], 0, json.dumps({
            "accessToken": TOKEN, "subscription": command[command.index("--subscription") + 1],
            "tenant": OTHER_TENANT if OTHER_SUB in command else TENANT,
        }), "",
    )
    result = verify(setup)
    assert {check["resource_id"] for check in result["checks"]} == {RG_ID, stage_id}
    assert all(check["verified"] for check in result["checks"])
    assert setup.runner.call_count == 2


@pytest.mark.parametrize("mode,attributes", [
    (stat.S_IFLNK, 0), (stat.S_IFREG, stat.FILE_ATTRIBUTE_REPARSE_POINT),
])
def test_snapshot_symlinks_and_junctions_are_rejected(setup, monkeypatch, mode, attributes):
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == setup.snapshot:
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(verification.VerificationRequestError):
        verify(setup)
    setup.service.overview.assert_not_called()
    setup.runner.assert_not_called()


@pytest.mark.parametrize("value", ["[]", "{invalid", '"not-an-object"'])
def test_malformed_snapshot_is_sanitized_before_inventory(setup, value):
    setup.snapshot.write_text(value)
    with pytest.raises(verification.VerificationRequestError):
        verify(setup)
    setup.service.overview.assert_not_called()


def test_duplicate_case_variants_share_one_fresh_get(setup):
    ref = copy.deepcopy(setup.env["resource_group_refs"][0])
    ref.update(id=ref["id"].upper(), name=ref["name"].upper())
    setup.env["resource_group_refs"].append(ref)
    result = verify(setup)
    assert len(result["checks"]) == 1 and result["checks"][0]["verified"]
    assert setup.opener.open.call_count == 1


def test_saved_foreign_factory_is_not_selected_by_project_number(setup):
    setup.snapshot.write_text(json.dumps({**setup.saved, "admin_aifactorySuffixRG": "-999"}))
    setup.current_path.write_text(json.dumps({**setup.saved, "project_number_000": "018"}))
    assert verify(setup)["checks"] == []
    setup.service.overview.assert_not_called()


@pytest.mark.parametrize("target,change", [
    ("snapshot", "identity"), ("snapshot", "unrelated"), ("snapshot", "delete"),
    ("current_path", "identity"), ("current_path", "unrelated"), ("current_path", "delete"),
    ("variables", "unrelated"),
])
def test_configuration_changes_during_successful_get_invalidate_evidence(setup, target, change):
    def changed(request, **kwargs):
        path = setup.root / "variables.json" if target == "variables" else getattr(setup, target)
        if change == "delete":
            path.unlink()
        else:
            value = {**setup.saved, **({"admin_location": "eastus2"} if change == "identity"
                                     else {"unrelated_config_value": TOKEN})}
            path.write_text(json.dumps(value))
        return response(request)
    setup.opener.open.side_effect = changed
    result = verify(setup)
    assert_not_verified(result)
    assert result["checks"][0]["http_status"] == 200
    assert "changed during verification" in result["message"]


def test_change_while_loading_inventory_stops_before_token(setup):
    def changed(*args, **kwargs):
        setup.snapshot.write_text(json.dumps({**setup.saved, "unrelated": True}))
        return setup.overview
    setup.service.overview.side_effect = changed
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_foreign_inventory_is_not_checked(setup):
    setup.overview["factory"]["prefix_rg"] = "foreign"
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_inventory_programming_errors_are_not_hidden(setup):
    setup.service.overview.side_effect = RuntimeError("programming defect")
    with pytest.raises(RuntimeError, match="programming defect"):
        verify(setup)


def test_api_auth_validation_and_sanitized_response_contract(setup, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    with TestClient(api.app) as client:
        assert client.post(ENDPOINT, json=setup.body).status_code == 401
        assert client.post(ENDPOINT, json=setup.body, headers={"X-API-Key": "wrong"}).status_code == 401
        setup.runner.assert_not_called()
        headers = {"X-API-Key": "test-key"}
        result = client.post(ENDPOINT, json=setup.body, headers=headers)
        assert result.status_code == 200
        assert set(result.json()) == {"project_number", "checked_at", "message", "checks"}
        assert set(result.json()["checks"][0]) == {"resource_id", "http_status", "verified", "message"}
        for changes in [{"project_number": "../017"}, {"project_number": 17}, {"path": None}]:
            assert client.post(ENDPOINT, json={**setup.body, **changes}, headers=headers).status_code == 422
        assert client.post(ENDPOINT, json={"project_number": "017"}, headers=headers).status_code == 422
        setup.runner.return_value = subprocess.CompletedProcess([], 1, TOKEN, TOKEN)
        failure = client.post(ENDPOINT, json=setup.body, headers=headers)
        assert failure.status_code == 200
        assert_not_verified(failure.json())
        setup.snapshot.unlink()
        assert client.post(ENDPOINT, json=setup.body, headers=headers).status_code == 404
        operation = client.get("/openapi.json").json()["paths"][ENDPOINT]["post"]
        assert operation["security"] == [{"APIKeyHeader": []}]
