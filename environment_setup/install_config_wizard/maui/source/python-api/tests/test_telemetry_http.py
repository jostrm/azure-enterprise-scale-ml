import base64
import io
import json
import subprocess
from email.message import Message
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

from src import operations
from src.operations import AzureCollectionError, AzureInventoryProvider, OperationsStore, _collection_warning
from telemetry_helpers import TENANT, TOKEN, TelemetryResponse, tables, token_result


SUB = "612e830e-b795-424e-ba5d-cd0a5dadecf4"
OTHER = "11111111-1111-4111-8111-111111111111"
APP_AUDIENCE = "https://api.applicationinsights.io"
LOG_AUDIENCE = "https://api.loganalytics.io"


@pytest.fixture
def store(tmp_path):
    return OperationsStore(tmp_path / "operations.db")


def resource(**changes):
    return {
        "id": f"/subscriptions/{SUB}/resourceGroups/factory-common-dev/providers/Microsoft.Insights/components/app",
        "subscriptionId": SUB, "name": "app", "tenantId": TENANT,
        "resourceGroup": "factory-common-dev",
        "type": "Microsoft.Insights/components",
        "properties": {"AppId": "app-id"},
    } | changes


def forbidden(*args, **kwargs):
    pytest.fail("No HTTP request may be sent after scope or token validation fails.")


def jwt(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.test-signature"


@pytest.mark.parametrize("application", [False, True])
def test_https_post_uses_explicit_subscription_token_and_endpoint_audience(store, application):
    audience = APP_AUDIENCE if application else LOG_AUDIENCE
    bearer = jwt({"tid": TENANT, "aud": audience})
    calls = []
    responses = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[1:] == [
            "account", "get-access-token", "--subscription", SUB,
            "--resource", audience, "--output", "json", "--only-show-errors",
        ]
        assert kwargs["shell"] is False
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["capture_output"] is True
        assert kwargs["env"]["AZURE_LOGGING_ENABLE_LOG_FILE"] == "false"
        assert kwargs["env"]["AZURE_CORE_LOG_LEVEL"] == "critical"
        return token_result(argv, token=bearer, resource=audience)

    def transport(request, **kwargs):
        assert request.get_method() == "POST"
        assert request.full_url == f"{audience}/v1/{'apps' if application else 'workspaces'}/target-id/query"
        assert request.headers["Content-type"] == "application/json"
        assert request.headers["Accept"] == "application/json"
        assert "Authorization" not in request.headers
        assert request.unredirected_hdrs["Authorization"] == f"Bearer {bearer}"
        assert 0 < kwargs["timeout"] <= 60
        assert bearer not in request.data.decode()
        response = TelemetryResponse(request, tables())
        responses.append(response)
        return response

    provider = AzureInventoryProvider(store, timeout=500, runner=runner, transport=transport)
    assert provider._telemetry_post(resource(), "target-id", application_insights=application) == tables()
    assert len(calls) == 1
    assert bearer not in json.dumps(calls)
    assert responses[0].closed
    assert responses[0].read_sizes == [operations._TELEMETRY_MAX_BYTES + 1]


@pytest.mark.parametrize("identity", [
    "", "../apps/else", "a/b", r"a\b", "?query=other", "x#part", "a%2fother",
    "https://elsewhere.invalid", "a\r\nAuthorization: other", "-id", "a" * 129, None, 7,
])
def test_endpoint_ids_cannot_change_origin_path_or_query(store, identity):
    provider = AzureInventoryProvider(store, runner=forbidden, transport=forbidden)
    with pytest.raises(AzureCollectionError, match="endpoint resource ID"):
        provider._telemetry_post(resource(), identity)


@pytest.mark.parametrize("overrides", [
    {"subscription": OTHER}, {"subscription": ""}, {"subscription": None},
    {"tenant": ""}, {"tenant": "not-a-tenant"}, {"tenant": None}, {"tenant": OTHER},
    {"accessToken": ""}, {"accessToken": None}, {"accessToken": "a" * 33000},
    {"accessToken": "Bearer unsafe"}, {"accessToken": "safe\r\nX-Injected: true"},
    {"tokenType": "Basic"}, {"resource": LOG_AUDIENCE}, {"audience": "https://evil.invalid"},
])
def test_wrong_or_missing_token_metadata_never_reaches_http(store, overrides):
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv, **overrides),
        transport=forbidden,
    )
    with pytest.raises(AzureCollectionError, match="Azure token") as caught:
        provider._query_app_insights(resource())
    warning = _collection_warning(resource(), caught.value)
    assert "Sign in again" in warning
    assert "Reader" not in warning
    assert TOKEN not in warning


@pytest.mark.parametrize("claims", [
    {"tid": OTHER, "aud": APP_AUDIENCE}, {"tid": TENANT, "aud": LOG_AUDIENCE},
    {"tid": TENANT}, {"aud": APP_AUDIENCE}, [], None,
])
def test_jwt_claims_must_agree_with_cli_tenant_and_endpoint(store, claims):
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv, token=jwt(claims)),
        transport=forbidden,
    )
    with pytest.raises(AzureCollectionError, match="Azure token claims"):
        provider._query_app_insights(resource())


def test_malformed_jwt_is_sanitized(store):
    bearer = "eyJheader.invalid.signature"
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv, token=bearer), transport=forbidden,
    )
    with pytest.raises(AzureCollectionError) as caught:
        provider._query_app_insights(resource())
    assert bearer not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("metadata", [
    {"tenantId": "invalid"}, {"tenant_id": OTHER}, {"_expected_tenant_id": OTHER},
    {"subscriptionId": OTHER},
])
def test_conflicting_resource_scope_prevents_even_token_acquisition(store, metadata):
    with pytest.raises(AzureCollectionError):
        AzureInventoryProvider(store, runner=forbidden, transport=forbidden)._query_app_insights(resource(**metadata))


def test_token_tenant_is_required_even_without_configured_tenant(store):
    item = resource()
    item.pop("tenantId")
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv, tenant=""),
        transport=forbidden,
    )
    with pytest.raises(AzureCollectionError, match="tenant"):
        provider._query_app_insights(item)


@pytest.mark.parametrize("failure", ["stderr", "stdout", "timeout", "oserror", "invalid-json", "large-json"])
def test_cli_token_failures_never_expose_captured_credentials(store, failure):
    leaked = f"Bearer {TOKEN} InvalidAuthenticationTokenTenant"

    def runner(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=leaked, stderr=leaked)
        if failure == "oserror":
            raise OSError(leaked)
        if failure == "invalid-json":
            return subprocess.CompletedProcess(argv, 0, leaked, "")
        if failure == "large-json":
            return subprocess.CompletedProcess(argv, 0, json.dumps({"accessToken": TOKEN, "padding": "x" * 65536}), "")
        return subprocess.CompletedProcess(argv, 1, leaked if failure == "stdout" else "", leaked if failure == "stderr" else "")

    provider = AzureInventoryProvider(store, runner=runner, transport=forbidden)
    with pytest.raises(AzureCollectionError) as caught:
        provider._query_app_insights(resource())
    assert TOKEN not in str(caught.value)
    warning = _collection_warning(resource(), caught.value)
    assert "Sign in again" in warning
    assert "Reader" not in warning


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("application", [False, True])
def test_default_transport_rejects_redirects_without_forwarding_token(store, monkeypatch, status, application):
    calls = []

    class FakeHTTPS(HTTPSHandler):
        def https_open(self, request):
            calls.append(request.full_url)
            headers = Message()
            headers["Location"] = "https://untrusted.invalid/stolen"
            response = addinfourl(io.BytesIO(b"{}"), headers, request.full_url, status)
            response.msg = "Redirect"
            return response

    monkeypatch.setattr(operations, "build_opener", lambda *handlers: build_opener(FakeHTTPS(), *handlers))
    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: token_result(argv))
    with pytest.raises(AzureCollectionError, match="redirects are not allowed"):
        provider._telemetry_post(resource(), "target-id", application_insights=application)
    assert len(calls) == 1
    assert "untrusted" not in calls[0]


@pytest.mark.parametrize("url", [
    "https://untrusted.invalid/query",
    "http://api.applicationinsights.io/v1/apps/app-id/query",
    "https://api.applicationinsights.io/v1/apps/other-app/query",
    "https://api.applicationinsights.io/v1/apps/app-id/query?extra=1",
])
def test_changed_response_identity_is_rejected_before_reading(store, url):
    responses = []

    def transport(request, **kwargs):
        response = TelemetryResponse(request, tables(), url=url)
        responses.append(response)
        return response

    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: token_result(argv), transport=transport)
    with pytest.raises(AzureCollectionError, match="response identity"):
        provider._query_app_insights(resource())
    assert responses[0].closed
    assert responses[0].read_sizes == []


@pytest.mark.parametrize("status,code,expected", [
    (401, "InvalidAuthenticationTokenTenant", "Sign in again"),
    (403, "InvalidAuthenticationTokenTenant", "Sign in again"),
    (403, "InsufficientAccessError", "review query access"),
    (403, "NspValidationFailedError", "network policy denied"),
    (400, "BadArgumentError", "BadArgumentError"),
    (429, "ThrottledError", "ThrottledError"),
    (500, "InternalServerError", "InternalServerError"),
])
def test_http_errors_remain_distinct_and_sanitized_without_same_endpoint_retry(store, status, code, expected):
    calls = []

    def transport(request, **kwargs):
        calls.append(request)
        raw = json.dumps({"error": {"code": code, "message": f"Bearer {TOKEN}"}}).encode()
        raise HTTPError(request.full_url, status, "failure", {}, io.BytesIO(raw))

    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: token_result(argv), transport=transport)
    with pytest.raises(AzureCollectionError) as caught:
        provider._query_app_insights(resource())
    assert len(calls) == 1
    assert TOKEN not in str(caught.value)
    assert expected in _collection_warning(resource(), caught.value)


@pytest.mark.parametrize("status", [200, 400, 401, 403])
def test_malformed_response_is_not_an_empty_success(store, status):
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv),
        transport=lambda request, **kwargs: TelemetryResponse(request, b"not json " + TOKEN.encode(), status=status),
    )
    with pytest.raises(AzureCollectionError, match="not valid JSON") as caught:
        provider._query_app_insights(resource())
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("status", [200, 403])
def test_response_and_error_size_limits_are_enforced_and_closed(store, monkeypatch, status):
    monkeypatch.setattr(operations, "_TELEMETRY_MAX_BYTES", 64)
    monkeypatch.setattr(operations, "_TELEMETRY_ERROR_BYTES", 32)
    responses = []

    def transport(request, **kwargs):
        response = TelemetryResponse(request, b"x" * 100, status=status)
        responses.append(response)
        return response

    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: token_result(argv), transport=transport)
    with pytest.raises(AzureCollectionError, match="size limit"):
        provider._query_app_insights(resource())
    assert responses[0].closed
    assert responses[0].read_sizes == [65 if status == 200 else 33]


@pytest.mark.parametrize("error", [
    TimeoutError(f"Bearer {TOKEN}"), URLError(f"Bearer {TOKEN}"), IncompleteRead(TOKEN.encode()),
])
def test_transport_failures_are_sanitized_and_not_retried(store, error):
    calls = []

    def transport(*args, **kwargs):
        calls.append(1)
        raise error

    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: token_result(argv), transport=transport)
    with pytest.raises(AzureCollectionError, match="failed or timed out") as caught:
        provider._query_app_insights(resource())
    assert len(calls) == 1
    assert TOKEN not in str(caught.value)


def test_partial_error_keeps_code_but_redacts_token_even_with_successful_tables(store):
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv),
        transport=lambda request, **kwargs: TelemetryResponse(
            request, tables({"operation_id": "partial"}) | {
                "error": {"code": "PartialError", "message": f"bad argument {TOKEN}", "accessToken": "other-secret"},
            },
        ),
    )
    with pytest.raises(AzureCollectionError, match="PartialError") as caught:
        provider._query_app_insights(resource())
    assert TOKEN not in str(caught.value)
    assert "other-secret" not in str(caught.value)


def test_factory_scope_tenant_checks_apply_per_resource_without_mutation_or_cross_factory_leak(store, tmp_path):
    item = resource()
    item.pop("tenantId")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["account", "show"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(TENANT), "")
        if argv[1:3] == ["group", "list"]:
            return subprocess.CompletedProcess(argv, 0, "[]", "")
        if argv[1:3] == ["resource", "list"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps([item]), "")
        return token_result(argv, tenant=OTHER)

    provider = AzureInventoryProvider(store, runner=runner, transport=forbidden)
    inventory = provider.get_inventory(
        str(tmp_path), [SUB], True, {"subscription_tenants": {SUB: TENANT}},
    )
    assert "Sign in again" in inventory["warning"]
    assert inventory["resources"] == [item]
    assert "_expected_tenant_id" not in json.dumps(item)
    assert inventory["telemetry"]["successful_prompt_queries"] == 0
    assert len(calls) == 4
    provider._telemetry_transport = lambda request, **kwargs: TelemetryResponse(request, tables())
    assert provider._query_app_insights(item) == []


def test_unexpected_transport_programming_error_is_not_hidden(store):
    def transport(*args, **kwargs):
        raise RuntimeError("programming defect")

    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: token_result(argv), transport=transport)
    with pytest.raises(RuntimeError, match="programming defect"):
        provider._query_app_insights(resource())


@pytest.mark.parametrize("payload", [
    [], None, {"tables": [None]}, {"tables": [{}]},
    {"tables": [{"columns": [], "rows": {}}]},
    {"tables": [{"columns": [None], "rows": []}]},
    {"tables": [{"columns": [{"name": "x"}], "rows": [[]]}]},
    {"tables": [{"columns": [{"name": "x"}], "rows": [[1, 2]]}]},
    {"tables": [{"columns": [{"name": "x"}, {"name": "x"}], "rows": [[1, 2]]}]},
])
def test_invalid_http_table_shape_is_not_silently_accepted_as_empty(store, payload):
    provider = AzureInventoryProvider(
        store, runner=lambda argv, **kwargs: token_result(argv),
        transport=lambda request, **kwargs: TelemetryResponse(request, payload),
    )
    with pytest.raises(AzureCollectionError):
        provider._query_app_insights(resource())
