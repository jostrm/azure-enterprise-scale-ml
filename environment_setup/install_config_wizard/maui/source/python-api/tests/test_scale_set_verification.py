import copy
import io
import json
import subprocess
from datetime import datetime, timedelta
from email.message import Message
from http.client import IncompleteRead
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

import pytest
from fastapi.testclient import TestClient

from src import api, operations, scale_set_verification as verification, wizard
from src.factory_scope import current_factory_scope
from src.operations import OperationsService


SUB = "11111111-1111-4111-8111-111111111111"
OTHER_SUB = "33333333-3333-4333-8333-333333333333"
TENANT = "22222222-2222-4222-8222-222222222222"
TOKEN = "private-test-access-token.DO_NOT_SERIALIZE"
NAME = "demo-esml-common-sdc-dev-007"
RG_ID = f"/subscriptions/{SUB}/resourceGroups/{NAME}"
ENDPOINT = "/api/v1/scale-sets/verify-resource-groups"


def response(resource_id=RG_ID, status=200, body=None, content_type="application/json", url=None):
    headers = Message()
    headers["Content-Type"] = content_type
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.getcode.return_value = status
    result.headers = headers
    result.read.return_value = json.dumps({"id": resource_id}).encode() if body is None else body
    result.geturl.return_value = url or f"{verification.ARM_ORIGIN}{RG_ID}?api-version=2021-04-01"
    return result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "factory"
    snapshots = root / "config-wizard" / "scalesets"
    snapshots.mkdir(parents=True)
    saved = {
        "admin_aifactoryPrefixRG": "demo-", "admin_aifactorySuffixRG": "-007",
        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "dev_sub_id": SUB, "test_sub_id": SUB, "prod_sub_id": SUB, "tenantId": TENANT,
    }
    current_path = root / "config-wizard" / "factory_state.json"
    current_path.write_text(json.dumps(saved))
    snapshot = snapshots / "scaleset_007.json"
    snapshot.write_text(json.dumps(saved))
    monkeypatch.setattr(operations, "resolve_azure_cli", lambda: "az.exe")
    scope = current_factory_scope(root)
    factory = {
        "folder": str(root), "prefix_rg": "demo-", "suffix_rg": "-007",
        "monitoring_regions": scope["monitoring_regions"], "subscription_ids": [SUB],
    }
    group = {"id": RG_ID, "name": NAME, "subscriptionId": SUB,
             "subscription_id": SUB, "location": "swedencentral", "tenant_id": TENANT}
    overview = {"factory": factory, "common_resource_groups": [group], "source": "cached"}
    service = Mock()
    service.overview.return_value = overview
    runner = Mock(return_value=subprocess.CompletedProcess(
        [], 0, json.dumps({"accessToken": TOKEN, "subscription": SUB, "tenant": TENANT}), "",
    ))
    opener = Mock()
    opener.open.return_value = response()
    monkeypatch.setattr(verification.subprocess, "run", runner)
    monkeypatch.setattr(verification, "build_opener", Mock(return_value=opener))
    monkeypatch.setattr(operations, "OperationsService", Mock(return_value=service))
    return SimpleNamespace(
        root=root, snapshot=snapshot, current_path=current_path, saved=saved,
        overview=overview, service=service, runner=runner, opener=opener, group=group,
        body={"aifactory_folder": str(root), "scale_set_id": "007", "path": str(snapshot)},
    )


def verify(setup):
    return verification.verify_resource_groups(**setup.body)


def assert_not_verified(result):
    assert not (result["checks"] and all(check["verified"] for check in result["checks"]))
    assert TOKEN not in json.dumps(result)


def test_inventory_programming_defects_are_not_hidden_as_azure_access_failures(setup):
    setup.service.overview.side_effect = RuntimeError("programming defect")
    with pytest.raises(RuntimeError, match="programming defect"):
        verify(setup)


def test_configuration_changed_during_http200_cannot_verify_current_scale_set(setup):
    def changed(*args, **kwargs):
        setup.snapshot.write_text(json.dumps({**setup.saved, "admin_location": "eastus2"}))
        return response()

    setup.opener.open.side_effect = changed
    result = verify(setup)
    assert result["checks"][0]["http_status"] == 200
    assert result["checks"][0]["verified"] is False
    assert "changed during verification" in result["message"]


def test_fresh_authenticated_200_uses_actual_subscription_and_no_account_mutation(setup, caplog):
    before = setup.snapshot.read_bytes(), setup.current_path.read_bytes()
    result = verify(setup)
    assert result["scale_set_id"] == "007"
    assert result["checks"][0]["verified"] is True
    assert result["checks"][0]["http_status"] == 200
    assert result["checks"][0]["resource_id"] == RG_ID
    assert result["checked_at"].endswith("Z")
    assert datetime.fromisoformat(result["checked_at"]).utcoffset() == timedelta(0)
    setup.service.overview.assert_called_once_with(str(setup.root), include_azure=True, force_refresh=False)
    argv, = setup.runner.call_args.args
    assert argv == ["az.exe", "account", "get-access-token", "--subscription", SUB,
                    "--resource", "https://management.azure.com/", "--output", "json", "--only-show-errors"]
    assert setup.runner.call_args.kwargs["timeout"] == 30
    assert setup.runner.call_args.kwargs["shell"] is False
    assert setup.runner.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert setup.runner.call_args.kwargs["env"]["AZURE_LOGGING_ENABLE_LOG_FILE"] == "false"
    request = setup.opener.open.call_args.args[0]
    assert request.full_url == f"https://management.azure.com{RG_ID}?api-version=2021-04-01"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer " + TOKEN
    assert setup.opener.open.call_args.kwargs["timeout"] == 20
    assert "Authorization" not in request.headers
    assert TOKEN not in json.dumps(result) + caplog.text
    assert before == (setup.snapshot.read_bytes(), setup.current_path.read_bytes())


@pytest.mark.parametrize("status", [202, 204, 301, 302, 307, 308, 401, 403, 404, 429, 500])
def test_only_exact_200_is_verified(setup, status):
    setup.opener.open.return_value = response(status=status)
    result = verify(setup)
    assert result["checks"][0]["http_status"] == status
    assert str(status) in result["checks"][0]["message"]
    assert_not_verified(result)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 404])
def test_http_errors_preserve_status_without_exposing_body(setup, status, caplog):
    setup.opener.open.side_effect = HTTPError(
        "https://management.azure.com", status, TOKEN, {}, io.BytesIO(TOKEN.encode()),
    )
    result = verify(setup)
    assert result["checks"][0]["http_status"] == status
    assert_not_verified(result)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("kwargs", [
    {"resource_id": RG_ID + "/providers/example/resources/one"},
    {"resource_id": RG_ID.replace(SUB, OTHER_SUB)},
    {"resource_id": RG_ID.replace("007", "001")},
    {"body": b"not JSON"},
    {"body": b'{"id":null}'},
    {"body": b"[]"},
    {"body": b'{"id":7}'},
    {"body": b"<html>Portal shell</html>", "content_type": "text/html"},
    {"url": "https://portal.azure.com/#@tenant/resource" + RG_ID},
    {"url": "https://management.azure.com.attacker.example"},
    {"body": b"x" * (verification.MAX_JSON_BYTES + 1)},
])
def test_malformed_or_unrelated_200_never_verifies(setup, kwargs):
    setup.opener.open.return_value = response(**kwargs)
    result = verify(setup)
    assert result["checks"][0]["http_status"] == 200
    assert_not_verified(result)


def test_resource_id_matching_is_case_insensitive(setup):
    setup.opener.open.return_value = response(resource_id=RG_ID.upper())
    assert verify(setup)["checks"][0]["verified"] is True


@pytest.mark.parametrize("error", [
    TimeoutError(TOKEN), URLError(TOKEN), OSError(TOKEN), IncompleteRead(TOKEN.encode()),
])
def test_transport_failure_does_not_raise_or_verify(setup, error):
    setup.opener.open.side_effect = error
    result = verify(setup)
    assert result["checks"][0]["http_status"] is None
    assert_not_verified(result)


def test_timeout_reading_200_body_is_unverified_transport_failure(setup):
    setup.opener.open.return_value.read.side_effect = TimeoutError(TOKEN)
    result = verify(setup)
    assert result["checks"][0]["http_status"] is None
    assert_not_verified(result)


@pytest.mark.parametrize("target", [
    "https://portal.azure.com/",
    "https://management.azure.com.attacker.example/steal",
    "https://management.azure.com/redirected",
])
def test_real_urllib_redirect_handler_never_forwards_authorization(setup, target):
    class FakeTransport(BaseHandler):
        handler_order = 100

        def __init__(self):
            self.requests = []

        def https_open(self, request):
            self.requests.append(request)
            headers = Message()
            headers["Location"] = target
            reply = addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
            reply.msg = "Found"
            return reply

    transport = FakeTransport()
    opener = build_opener(transport, verification._NoRedirect())
    result = verification.verify_resource_groups(**setup.body, opener=opener)
    assert len(transport.requests) == 1
    assert transport.requests[0].full_url.startswith("https://management.azure.com/subscriptions/")
    assert result["checks"][0]["http_status"] == 302
    assert_not_verified(result)


@pytest.mark.parametrize("result", [
    subprocess.CompletedProcess([], 1, TOKEN, TOKEN),
    subprocess.CompletedProcess([], 0, TOKEN, ""),
    subprocess.CompletedProcess([], 0, "[]", ""),
    subprocess.CompletedProcess([], 0, json.dumps({"subscription": OTHER_SUB, "tenant": TENANT, "accessToken": TOKEN}), ""),
    subprocess.CompletedProcess([], 0, json.dumps({"subscription": SUB, "tenant": OTHER_SUB, "accessToken": TOKEN}), ""),
    subprocess.CompletedProcess([], 0, json.dumps({"subscription": SUB, "tenant": TENANT, "accessToken": "a\r\nb"}), ""),
    subprocess.CompletedProcess([], 0, json.dumps({"subscription": SUB, "tenant": TENANT}), ""),
])
def test_cli_errors_are_sanitized_and_never_make_resource_request(setup, result, caplog):
    setup.runner.return_value = result
    actual = verify(setup)
    assert_not_verified(actual)
    assert actual["checks"][0]["http_status"] is None
    setup.opener.open.assert_not_called()
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("error", [
    FileNotFoundError(TOKEN), subprocess.TimeoutExpired(["az"], 30, output=TOKEN),
    subprocess.CalledProcessError(1, ["az"], output=TOKEN, stderr=TOKEN),
])
def test_token_transport_failures_are_unverified_and_sanitized(setup, error):
    setup.runner.side_effect = error
    result = verify(setup)
    assert_not_verified(result)
    setup.opener.open.assert_not_called()


def test_missing_cli_is_not_an_api_failure(setup, monkeypatch):
    monkeypatch.setattr(operations, "resolve_azure_cli", Mock(side_effect=RuntimeError(TOKEN)))
    assert_not_verified(verify(setup))
    setup.runner.assert_not_called()


def test_multi_group_partial_failure_and_duplicate_deduplication(setup):
    group2 = {**setup.group, "name": NAME.replace("dev", "prod"), "id": RG_ID.replace("dev", "prod")}
    setup.overview["common_resource_groups"] = [setup.group, copy.deepcopy(setup.group), group2]
    setup.opener.open.side_effect = [response(), HTTPError("", 404, TOKEN, {}, None)]
    result = verify(setup)
    assert [check["verified"] for check in result["checks"]] == [True, False]
    assert len(result["checks"]) == 2
    assert setup.runner.call_count == 1
    assert setup.opener.open.call_count == 2
    assert_not_verified(result)


def test_each_subscription_gets_its_own_token(setup):
    current = {**setup.saved, "prod_sub_id": OTHER_SUB}
    setup.current_path.write_text(json.dumps(current))
    setup.snapshot.write_text(json.dumps(current))
    setup.overview["factory"]["subscription_ids"] = [SUB, OTHER_SUB]
    group2 = {**setup.group, "name": NAME.replace("dev", "prod"),
              "id": RG_ID.replace(SUB, OTHER_SUB).replace("dev", "prod"),
              "subscriptionId": OTHER_SUB, "subscription_id": OTHER_SUB}
    setup.overview["common_resource_groups"].append(group2)
    setup.runner.side_effect = [
        subprocess.CompletedProcess([], 0, json.dumps(
            {"subscription": sub, "tenant": TENANT, "accessToken": TOKEN}), "")
        for sub in (SUB, OTHER_SUB)
    ]
    setup.opener.open.side_effect = [
        response(), response(resource_id=group2["id"], url=f"{verification.ARM_ORIGIN}{group2['id']}?api-version=2021-04-01"),
    ]
    assert all(check["verified"] for check in verify(setup)["checks"])
    assert [call.args[0][call.args[0].index("--subscription") + 1]
            for call in setup.runner.call_args_list] == [SUB, OTHER_SUB]


@pytest.mark.parametrize("changes", [
    {"admin_aifactoryPrefixRG": "foreign-"},
    {"admin_location": "westeurope"},
    {"dev_sub_id": OTHER_SUB},
    {"test_sub_id": OTHER_SUB},
    {"prod_sub_id": "invalid-subscription"},
    {"test_sub_id": 7},
    {"dev_sub_id": "", "test_sub_id": "", "prod_sub_id": ""},
    {"admin_location": ""},
    {"admin_aifactoryPrefixRG": ""},
])
def test_saved_scope_mismatch_never_loads_inventory_or_calls_azure(setup, changes):
    setup.snapshot.write_text(json.dumps({**setup.saved, **changes}))
    result = verify(setup)
    assert result["checks"] == []
    assert_not_verified(result)
    setup.service.overview.assert_not_called()
    setup.runner.assert_not_called()
    setup.opener.open.assert_not_called()


def test_other_saved_scale_set_id_never_uses_active_007_groups(setup):
    other = setup.snapshot.with_name("scaleset_001.json")
    other.write_text(json.dumps({**setup.saved, "admin_aifactorySuffixRG": "-001"}))
    setup.body.update(scale_set_id="001", path=str(other))
    assert verify(setup)["checks"] == []
    setup.service.overview.assert_not_called()
    setup.runner.assert_not_called()


def test_normalized_scope_matches_without_defaults(setup):
    setup.snapshot.write_text(json.dumps({
        **setup.saved, "admin_aifactoryPrefixRG": "DEMO_", "admin_location": "SWEDENCENTRAL",
    }))
    assert verify(setup)["checks"][0]["verified"] is True


@pytest.mark.parametrize("changes", [
    {"monitoring_regions": ["westeurope"]}, {"subscription_ids": [OTHER_SUB]},
    {"prefix_rg": "foreign-"}, {"suffix_rg": "-001"}, {"folder": "unrelated"},
])
def test_inventory_scope_mismatch_never_verifies(setup, changes):
    setup.overview["factory"].update(changes)
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_inventory_exception_is_not_exposed(setup):
    setup.service.overview.side_effect = operations.AzureCollectionError(TOKEN)
    assert_not_verified(verify(setup))
    setup.runner.assert_not_called()


def test_scope_change_during_inventory_discovery_is_rejected(setup):
    def overview(*args, **kwargs):
        setup.current_path.write_text(json.dumps({**setup.saved, "admin_location": "westeurope"}))
        return setup.overview
    setup.service.overview.side_effect = overview
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_no_observed_common_groups_is_not_a_success(setup):
    setup.overview["common_resource_groups"] = []
    result = verify(setup)
    assert result["checks"] == []
    assert_not_verified(result)
    setup.runner.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"name": NAME.replace("common", "project017"), "id": RG_ID.replace("common", "project017")},
    {"name": NAME.replace("007", "001"), "id": RG_ID.replace("007", "001")},
    {"location": "westeurope"},
    {"id": RG_ID.replace(SUB, OTHER_SUB), "subscriptionId": OTHER_SUB, "subscription_id": OTHER_SUB},
])
def test_project_and_foreign_groups_are_never_requested(setup, changes):
    setup.group.update(changes)
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"id": "https://management.azure.com.attacker.example" + RG_ID},
    {"id": "https://portal.azure.com/#resource" + RG_ID},
    {"id": RG_ID + "/providers/Microsoft.Compute/virtualMachines/one"},
    {"id": RG_ID + "?token=unsafe"},
    {"id": RG_ID + "#portal"},
    {"id": RG_ID.replace("007", "008")},
    {"subscriptionId": OTHER_SUB},
    {"subscription_id": "invalid"},
    {"id": "", "subscriptionId": "", "subscription_id": ""},
    {"id": RG_ID.replace(SUB, "bad-id")},
])
def test_invalid_observed_identity_is_fail_closed(setup, changes):
    setup.group.update(changes)
    assert verify(setup)["checks"] == []
    setup.runner.assert_not_called()


def test_missing_rg_id_uses_only_valid_observed_name_and_subscription(setup):
    setup.group["id"] = ""
    assert verify(setup)["checks"][0]["resource_id"] == RG_ID
    assert setup.opener.open.call_args.args[0].full_url.startswith(verification.ARM_ORIGIN + RG_ID)


def test_limit_is_not_silently_truncated_into_success(setup):
    setup.overview["common_resource_groups"] = [
        {**setup.group, "name": NAME.replace("esml", f"esml{index}"),
         "id": RG_ID.replace("esml", f"esml{index}")} for index in range(13)
    ]
    result = verify(setup)
    assert result["checks"] == []
    assert "12" in result["message"]
    setup.runner.assert_not_called()


def test_cached_inventory_status_is_never_cached_verification(setup):
    assert verify(setup)["checks"][0]["verified"] is True
    setup.opener.open.return_value = response(status=404)
    assert_not_verified(verify(setup))
    assert setup.opener.open.call_count == 2
    assert setup.runner.call_count == 2


def test_real_operations_matching_cache_skips_discovery_cli_but_always_gets_rg(setup, tmp_path):
    store = operations.OperationsStore(tmp_path / "operations.db")

    def collect(argv, **kwargs):
        data = TENANT if "account" in argv else [setup.group] if "group" in argv else []
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    inventory_runner = Mock(side_effect=collect)
    inventory = operations.AzureInventoryProvider(store, runner=inventory_runner, azure_cli="az.exe")
    inventory._collect_telemetry = Mock(return_value=({}, []))
    service = OperationsService(store=store, inventory=inventory)
    local = service.discovery.discover(str(setup.root))
    inventory.get_inventory(str(setup.root), local["subscription_ids"], force_refresh=True, factory=local)
    inventory_runner.reset_mock()
    for _ in range(2):
        result = verification.verify_resource_groups(**setup.body, service=service)
        assert result["checks"][0]["verified"] is True
    inventory_runner.assert_not_called()
    assert setup.opener.open.call_count == 2


def test_real_operations_rejects_stale_cache_when_full_monitoring_targets_change(setup, tmp_path):
    store = operations.OperationsStore(tmp_path / "operations.db")

    def collect(argv, **kwargs):
        data = TENANT if "account" in argv else [setup.group] if "group" in argv else []
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    inventory_runner = Mock(side_effect=collect)
    inventory = operations.AzureInventoryProvider(store, runner=inventory_runner, azure_cli="az.exe")
    inventory._collect_telemetry = Mock(return_value=({}, []))
    service = OperationsService(store=store, inventory=inventory)
    local = service.discovery.discover(str(setup.root))
    inventory.get_inventory(str(setup.root), local["subscription_ids"], force_refresh=True, factory=local)
    # Same subscription, prefix, suffix, and region; only the monitored name suffix changes.
    changed = {**setup.saved, "admin_locationSuffix": "newregion"}
    setup.current_path.write_text(json.dumps(changed))
    inventory_runner.reset_mock()
    inventory_runner.side_effect = lambda argv, **kwargs: subprocess.CompletedProcess(
        argv, 1, "", "Offline during unit test",
    )
    result = verification.verify_resource_groups(**setup.body, service=service)
    assert inventory_runner.call_count > 0
    assert result["checks"] == []
    setup.opener.open.assert_not_called()


@pytest.mark.parametrize("change,status", [
    ({"path": "relative.json"}, 400),
    ({"aifactory_folder": "relative"}, 400),
    ({"scale_set_id": "../007"}, 400),
    ({"scale_set_id": "007."}, 400),
    ({"scale_set_id": "--option"}, 400),
    ({"scale_set_id": "008"}, 404),
])
def test_invalid_selection_is_sanitized_before_inventory(setup, change, status):
    setup.body.update(change)
    with pytest.raises(verification.VerificationRequestError) as error:
        verify(setup)
    assert error.value.status_code == status
    setup.service.overview.assert_not_called()


def test_wrong_existing_path_is_rejected(setup):
    other = setup.snapshot.with_name("scaleset_008.json")
    other.write_text(json.dumps(setup.saved))
    setup.body["path"] = str(other)
    with pytest.raises(verification.VerificationRequestError) as error:
        verify(setup)
    assert error.value.status_code == 409
    setup.runner.assert_not_called()


@pytest.mark.parametrize("owner", ["other", "missing", "matching"])
def test_legacy_snapshot_owner_and_exact_current_listing(setup, monkeypatch, owner):
    legacy = setup.root.parent / "legacy"
    legacy.mkdir()
    path = legacy / "scaleset_007.json"
    saved = dict(setup.saved)
    if owner != "missing":
        saved["_save_folder"] = str(setup.root if owner == "matching" else setup.root.parent / "other")
    path.write_text(json.dumps(saved))
    calls = []
    def listing(folder, *, create_legacy_dir):
        calls.append(create_legacy_dir)
        return {"007": str(path)}
    monkeypatch.setattr(wizard, "_list_scalesets", listing)
    setup.body["path"] = str(path)
    if owner == "other":
        with pytest.raises(verification.VerificationRequestError) as error:
            verify(setup)
        assert error.value.status_code == 409
        setup.runner.assert_not_called()
    else:
        assert verify(setup)["checks"][0]["verified"] is True
    assert calls and not any(calls)


@pytest.mark.parametrize("content", ["{", "[]", '{"admin_aifactorySuffixRG": "-008"}'])
def test_snapshot_is_raw_not_default_hydrated(setup, content):
    setup.snapshot.write_text(content)
    with pytest.raises(verification.VerificationRequestError):
        verify(setup)
    setup.runner.assert_not_called()


def test_api_auth_validation_and_sanitized_result(setup, monkeypatch):
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    with TestClient(api.app) as client:
        assert client.post(ENDPOINT, json=setup.body).status_code == 401
        assert client.post(ENDPOINT, json=setup.body, headers={"X-API-Key": "wrong"}).status_code == 401
        setup.runner.assert_not_called()
        headers = {"X-API-Key": "test-key"}
        result = client.post(ENDPOINT, json=setup.body, headers=headers)
        assert result.status_code == 200
        assert set(result.json()) == {"scale_set_id", "checked_at", "message", "checks"}
        assert TOKEN not in result.text
        invalid = client.post(ENDPOINT, json={**setup.body, "scale_set_id": "../007"}, headers=headers)
        assert invalid.status_code == 400
        missing = client.post(ENDPOINT, json={"aifactory_folder": str(setup.root)}, headers=headers)
        assert missing.status_code == 422
        setup.runner.return_value = subprocess.CompletedProcess([], 1, TOKEN, TOKEN)
        failure = client.post(ENDPOINT, json=setup.body, headers=headers)
        assert failure.status_code == 200
        assert_not_verified(failure.json())
        operation = client.get("/openapi.json").json()["paths"][ENDPOINT]["post"]
        assert operation["security"] == [{"APIKeyHeader": []}]


def test_checked_in_openapi_matches_generated_contract():
    from pathlib import Path
    checked_in = json.loads((Path(__file__).parents[1] / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert checked_in == api.app.openapi()
