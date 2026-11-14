"""Provider traffic is intercepted: these tests never dispatch a real pipeline."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
SPEC = importlib.util.spec_from_file_location("pipeline_dispatch", ROOT / "bootstrap/lib/pipeline_dispatch.py")
dispatch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatch)

CORRELATION = "a" * 32
COMMIT = "b" * 40
SOURCE = "c" * 40


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live network is forbidden"))


def request(provider, scenario=1):
    return {"schema": 1, "provider": provider, "scenario": scenario, "factory": "factory",
            "environment": "dev", "source_ref": "refs/heads/main", "source_commit": SOURCE}


def binding(provider):
    value = {"schema": 1, "provider": provider, "consumer_commit": COMMIT,
             "consumer_ref": "refs/heads/main",
             "repository": "https://github.com/acme/factory" if provider == "gha"
             else "https://dev.azure.com/acme/project/_git/factory"}
    if provider == "ado":
        value["pipeline_id"] = 9
    return value


class Traffic:
    def __init__(self, provider, result="success", *, rerun=False, pages=False):
        self.provider, self.result, self.rerun, self.pages = provider, result, rerun, pages
        self.calls, self.posted, self.observations = [], False, 0
        self.artifact_download_url = "https://dev.azure.com/acme/project/_apis/build/builds/7/artifacts?format=zip"

    def request(self, method, url, body=None, raw=False):
        self.calls.append((method, url, body))
        if method == "POST":
            assert not self.posted, "ambiguous writes must never be retried"
            self.posted = True
            return (204, {}, None) if self.provider == "gha" else (200, {}, self.run())
        if "/commits/" in url:
            return 200, {}, {"sha": COMMIT}
        if url.endswith("/workflows/pipelines-only-gha.yml"):
            return 200, {}, {"id": 9, "path": ".github/workflows/pipelines-only-gha.yml", "state": "active"}
        if "/build/definitions/9?" in url:
            return 200, {}, {"id": 9, "process": {"yamlFilename": "pipelines-only-ado.yml"},
                             "repository": {"url": binding("ado")["repository"]}}
        if "/workflows/9/runs?" in url:
            if self.pages and "page=2" not in url:
                return 200, {"link": '<https://api.github.com/ignored>; rel="next"'}, {
                    "workflow_runs": [dict(self.run(), id=3, display_title="unrelated")]}
            return 200, {}, {"workflow_runs": [self.run()] if self.posted else []}
        if "/artifacts" in url:
            if raw:
                content = io.BytesIO()
                with zipfile.ZipFile(content, "w") as archive:
                    archive.writestr("receipt.json", json.dumps({"outcome": "completed"}))
                return 200, {}, content.getvalue()
            name = f"esaf-receipt-{CORRELATION}-1"
            if self.provider == "gha":
                return 200, {}, {"artifacts": [{"id": 44, "name": name, "expired": False}]}
            return 200, {}, {"value": [{"name": name, "resource": {
                "downloadUrl": self.artifact_download_url}}]}
        self.observations += 1
        return 200, {}, self.run()

    def run(self):
        if self.provider == "gha":
            return {"id": 7, "workflow_id": 9, "event": "workflow_dispatch",
                    "display_title": f"pipelines-only [{CORRELATION}]", "head_sha": COMMIT,
                    "run_attempt": 2 if self.rerun else 1, "status": "completed",
                    "conclusion": self.result, "repository": {"full_name": "acme/factory"}}
        return {"id": 7, "pipeline": {"id": 9}, "state": "completed",
                "result": self.result, "resources": {"repositories": {"self": {"version": COMMIT}}},
                "templateParameters": {"correlation_id": CORRELATION,
                                       "request_digest": dispatch.digest(request("ado"))}}


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
def test_dispatch_wait_requires_provider_and_lifecycle_success(provider, scenario):
    traffic = Traffic(provider, "success" if provider == "gha" else "succeeded")
    canonical = request(provider, scenario)
    if provider == "ado":
        old_run = traffic.run
        traffic.run = lambda: dict(old_run(), templateParameters={
            "correlation_id": CORRELATION, "request_digest": dispatch.digest(canonical)})
    checked = []
    def verify(receipt, expected):
        checked.append((receipt, expected))
        return {"outcome": "completed"}
    result = dispatch.dispatch_and_wait("requests/run.json", canonical, binding(provider),
                                        transport=traffic, verify=verify, correlation_id=CORRELATION,
                                        sleep=lambda _: None, max_polls=2)
    assert result["outcome"] == "completed" and checked
    assert checked[0][1]["request_digest"] == dispatch.digest(canonical)
    assert checked[0][1]["run_id"] == 7
    assert len([call for call in traffic.calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("provider,result", [
    ("gha", "failure"), ("gha", "cancelled"), ("gha", "skipped"), ("gha", "neutral"),
    ("ado", "failed"), ("ado", "canceled"), ("ado", "partiallySucceeded"),
])
def test_non_success_never_downloads_or_accepts_receipt(provider, result):
    traffic = Traffic(provider, result)
    with pytest.raises(dispatch.DispatchError, match="provider-run-unsuccessful"):
        dispatch.dispatch_and_wait("requests/run.json", request(provider), binding(provider),
                                   transport=traffic, verify=lambda *_: pytest.fail("not reached"),
                                   correlation_id=CORRELATION, sleep=lambda _: None, max_polls=2)
    assert not any("/artifacts" in call[1] for call in traffic.calls)


def test_paginated_exact_correlation_and_attempt():
    traffic = Traffic("gha", pages=True)
    dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"), transport=traffic,
                               verify=lambda *_: {"outcome": "completed"},
                               correlation_id=CORRELATION, sleep=lambda _: None, max_polls=2)
    assert any("page=2" in call[1] for call in traffic.calls)
    traffic = Traffic("gha", rerun=True)
    with pytest.raises(dispatch.DispatchError, match="run-identity"):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"), transport=traffic,
                                   verify=lambda *_: {"outcome": "completed"},
                                   correlation_id=CORRELATION, sleep=lambda _: None, max_polls=2)


def test_provider_success_is_not_lifecycle_success():
    with pytest.raises(dispatch.DispatchError, match="lifecycle-not-completed"):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"),
                                   transport=Traffic("gha"), verify=lambda *_: {"outcome": "waiting"},
                                   correlation_id=CORRELATION, sleep=lambda _: None, max_polls=2)


def test_real_runtime_verifier_never_accepts_bare_success_json():
    with pytest.raises((dispatch.DispatchError, ValueError)):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"),
                                   transport=Traffic("gha"), correlation_id=CORRELATION,
                                   sleep=lambda _: None, max_polls=2)


def test_mismatched_provider_and_untrusted_workflow_fail_before_network():
    traffic = Traffic("gha")
    for bad in [binding("ado"), dict(binding("gha"), workflow="../../evil.yml")]:
        with pytest.raises(dispatch.DispatchError):
            dispatch.dispatch_and_wait("request.json", request("gha"), bad, transport=traffic,
                                       verify=lambda *_: {}, correlation_id=CORRELATION)
    assert traffic.calls == []


def test_stale_id_cannot_be_rediscovered_as_a_new_dispatch():
    traffic = Traffic("gha")
    original = traffic.request
    def stale(method, url, body=None, raw=False):
        if "/workflows/9/runs?" in url:
            return 200, {}, {"workflow_runs": [traffic.run()]}
        return original(method, url, body, raw)
    traffic.request = stale
    with pytest.raises(dispatch.DispatchError, match="dispatch-unconfirmed"):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"), transport=traffic,
                                   verify=lambda *_: pytest.fail("stale receipt must not be used"),
                                   correlation_id=CORRELATION, max_polls=2, sleep=lambda _: None)
    assert len([call for call in traffic.calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_nonterminal_run_times_out_without_success(provider):
    traffic = Traffic(provider)
    original = traffic.run
    traffic.run = lambda: dict(original(), status="in_progress", state="inProgress")
    with pytest.raises(dispatch.DispatchError, match="wait-timeout-not-completed"):
        dispatch.dispatch_and_wait("request.json", request(provider), binding(provider), transport=traffic,
                                   verify=lambda *_: pytest.fail("not reached"), correlation_id=CORRELATION,
                                   max_polls=2, sleep=lambda _: None)


def test_duplicate_correlated_runs_and_pagination_cap_fail_closed():
    traffic = Traffic("gha")
    original = traffic.request
    def duplicate(method, url, body=None, raw=False):
        if traffic.posted and "/workflows/9/runs?" in url:
            return 200, {}, {"workflow_runs": [traffic.run(), dict(traffic.run(), id=8)]}
        return original(method, url, body, raw)
    traffic.request = duplicate
    with pytest.raises(dispatch.DispatchError, match="correlation-ambiguous"):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"), transport=traffic,
                                   verify=lambda *_: {}, correlation_id=CORRELATION)
    traffic.request = lambda *_: (200, {"link": '<ignored>; rel="next"'}, {"workflow_runs": []})
    with pytest.raises(dispatch.DispatchError, match="pagination-limit"):
        dispatch._pages(traffic, "https://api.github.com/ignored", "workflow_runs", max_pages=2)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_uncertain_dispatch_is_never_retried(provider):
    traffic = Traffic(provider)
    original = traffic.request
    posts = []
    def fail(method, url, body=None, raw=False):
        if method == "POST":
            posts.append(url)
            raise dispatch.DispatchError("transport-lost-after-write")
        return original(method, url, body, raw)
    traffic.request = fail
    with pytest.raises(dispatch.DispatchError, match="transport-lost"):
        dispatch.dispatch_and_wait("request.json", request(provider), binding(provider), transport=traffic,
                                   verify=lambda *_: {}, correlation_id=CORRELATION)
    assert len(posts) == 1


def test_nested_canonical_registration_controls_route():
    canonical = {"request": request("gha"), "binding": {"repository": "https://github.com/acme/other",
                                                       "orchestrator": "gha", "ref": "refs/heads/main"}}
    traffic = Traffic("gha")
    with pytest.raises(dispatch.DispatchError, match="provider-route-mismatch"):
        dispatch.dispatch_and_wait("request.json", canonical, binding("gha"), transport=traffic)
    assert traffic.calls == []


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_accelerator_ref_does_not_select_consumer_pipeline_ref(provider):
    canonical = {"request": dict(request(provider), source_ref="refs/tags/accelerator-v1.25"),
                 "binding": {"repository": binding(provider)["repository"],
                             "orchestrator": provider, "ref": "refs/heads/main"}}
    traffic = Traffic(provider, "success" if provider == "gha" else "succeeded")
    if provider == "ado":
        original = traffic.run
        traffic.run = lambda: dict(original(), templateParameters={
            "correlation_id": CORRELATION, "request_digest": dispatch.digest(canonical)})
    dispatch.dispatch_and_wait("request.json", canonical, binding(provider), transport=traffic,
                               verify=lambda *_: {"outcome": "completed"}, correlation_id=CORRELATION)
    post = next(body for method, _, body in traffic.calls if method == "POST")
    actual = post["ref"] if provider == "gha" else post["resources"]["repositories"]["self"]["refName"]
    assert actual == "refs/heads/main"
    assert all("accelerator-v1.25" not in url for _, url, _ in traffic.calls)


def test_missing_or_conflicting_consumer_ref_is_not_inferred_from_accelerator():
    traffic = Traffic("gha")
    configured = binding("gha")
    del configured["consumer_ref"]
    with pytest.raises(dispatch.DispatchError, match="explicit-consumer-ref-required"):
        dispatch.dispatch_and_wait("request.json", request("gha"), configured, transport=traffic)
    canonical = {"request": request("gha"), "binding": {
        "repository": configured["repository"], "orchestrator": "gha", "ref": "refs/heads/main"}}
    with pytest.raises(dispatch.DispatchError, match="consumer-ref-native-binding-mismatch"):
        dispatch.dispatch_and_wait("request.json", canonical,
                                   dict(configured, consumer_ref="refs/heads/other"), transport=traffic)
    assert traffic.calls == []


def test_wrong_run_receipt_or_absent_artifact_cannot_green():
    traffic = Traffic("gha")
    original = traffic.request
    def missing(method, url, body=None, raw=False):
        if "/artifacts" in url:
            return 200, {}, {"artifacts": [{"id": 44, "name": "esaf-receipt-other-1", "expired": False}]}
        return original(method, url, body, raw)
    traffic.request = missing
    with pytest.raises(dispatch.DispatchError, match="receipt-artifact-missing"):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"), transport=traffic,
                                   verify=lambda *_: {}, correlation_id=CORRELATION)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_real_transport_keeps_credentials_out_of_payload_and_argv(monkeypatch, provider):
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "test-token")
    class Response(io.BytesIO):
        status = 200
        headers = {}
    seen = []
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            return Response(b'{"id":7}')
    base = dispatch.validate_binding(request(provider), binding(provider))
    transport = dispatch.ProviderTransport(provider, base, opener=Opener())
    assert transport.request("POST", base + "/test", {"request": "value"})[2] == {"id": 7}
    assert seen[0].get_header("Authorization") == "Bearer test-token"
    assert b"test-token" not in seen[0].data
    with pytest.raises(dispatch.DispatchError, match="outside-binding"):
        transport.request("GET", "https://attacker.invalid/test")


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_artifact_redirect_never_forwards_provider_token(monkeypatch, provider):
    from urllib.error import HTTPError
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "test-token")
    class Response(io.BytesIO):
        status = 200
        headers = {}
    seen = []
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            if len(seen) == 1:
                raise HTTPError(req.full_url, 302, "redirect",
                                {"Location": "https://objects.blob.core.windows.net/signed?sig=test"}, None)
            return Response(b"archive")
    base = dispatch.validate_binding(request(provider), binding(provider))
    transport = dispatch.ProviderTransport(provider, base, opener=Opener())
    assert transport.request("GET", base + "/artifact/zip", raw=True)[2] == b"archive"
    assert seen[0].get_header("Authorization") and seen[1].get_header("Authorization") is None


@pytest.mark.parametrize("download_url", [
    "https://dev.azure.com/acme/project/_apis/build/builds/7/artifacts?format=zip",
    "https://dev.azure.com/acme/11111111-2222-4333-8444-555555555555/_apis/build/builds/7/artifacts?format=zip",
    "https://dev.azure.com/acme/other-project/_apis/build/builds/7/artifacts?format=zip",
    "https://dev.azure.com/other-org/project/_apis/build/builds/7/artifacts?format=zip",
    "https://attacker.invalid/acme/project/_apis/build/builds/7/artifacts?format=zip",
    "https://dev.azure.com/acme/project/_apis/build/builds/999/artifacts?artifactName=other&format=zip",
])
def test_ado_receipt_content_uses_verified_route_not_metadata_url(monkeypatch, download_url):
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "offline-token")
    traffic = Traffic("ado", "succeeded")
    traffic.artifact_download_url = download_url
    base = dispatch.validate_binding(request("ado"), binding("ado"))
    downloads = []

    class Response(io.BytesIO):
        def __init__(self, status, headers, body):
            super().__init__(body)
            self.status, self.headers = status, headers

    class InterceptHTTP:
        def open(self, req, timeout):
            assert req.full_url.startswith(base + "/")
            assert req.get_header("Authorization")
            query = parse_qs(urlsplit(req.full_url).query)
            raw = query.get("$format") == ["zip"] or query.get("format") == ["zip"]
            if raw:
                assert req.full_url.split("?", 1)[0] == base + "/build/builds/7/artifacts"
                assert query == {"artifactName": [f"esaf-receipt-{CORRELATION}-1"],
                                 "$format": ["zip"], "api-version": ["7.1"]}
                downloads.append(req.full_url)
            payload = json.loads(req.data) if req.data else None
            status, headers, value = traffic.request(req.method, req.full_url, payload, raw)
            return Response(status, headers, value if raw else json.dumps(value).encode())

    transport = dispatch.ProviderTransport("ado", base, opener=InterceptHTTP())
    result = dispatch.dispatch_and_wait("request.json", request("ado"), binding("ado"), transport=transport,
                                        verify=lambda *_: {"outcome": "completed"},
                                        correlation_id=CORRELATION, sleep=lambda _: None)
    assert result["outcome"] == "completed" and len(downloads) == 1
    assert downloads[0] != download_url


@pytest.mark.parametrize("target", [
    "https://attacker.invalid/receipt.zip",
    "https://dev.azure.com/acme/other-project/_apis/build/builds/7/artifacts",
    "https://objects.blob.core.windows.net.attacker.invalid/receipt.zip",
    "http://objects.blob.core.windows.net/receipt.zip",
    "https://user@objects.blob.core.windows.net/receipt.zip",
    "https://objects.blob.core.windows.net:444/receipt.zip",
])
def test_ado_artifact_unvalidated_redirects_remain_rejected(monkeypatch, target):
    from urllib.error import HTTPError
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "offline-token")
    seen = []

    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            raise HTTPError(req.full_url, 302, "redirect", {"Location": target}, None)

    base = dispatch.validate_binding(request("ado"), binding("ado"))
    transport = dispatch.ProviderTransport("ado", base, opener=Opener())
    with pytest.raises(dispatch.DispatchError, match="artifact-redirect-outside-provider"):
        transport.request("GET", base + "/build/builds/7/artifacts?%24format=zip", raw=True)
    assert len(seen) == 1 and seen[0].get_header("Authorization")


@pytest.mark.parametrize("project", ["Project%20Name", "11111111-2222-4333-8444-555555555555"])
def test_ado_artifact_content_query_encodes_exact_name(project):
    configured = dict(binding("ado"), repository=f"https://dev.azure.com/acme/{project}/_git/factory")
    base = dispatch.validate_binding(request("ado"), configured)
    name = "inputs + &artifactName=other/#%"
    url = dispatch._ado_artifact_content_url(base, 123, name)
    parsed = urlsplit(url)
    assert url.split("?", 1)[0] == base + "/build/builds/123/artifacts"
    assert parsed.fragment == ""
    assert parse_qs(parsed.query) == {"artifactName": [name], "$format": ["zip"], "api-version": ["7.1"]}


@pytest.mark.parametrize("path", ["../request.json", "/request.json", "x\\request.json", "x/../y", "x\nbad", "x:y"])
def test_unsafe_request_path_fails_before_network(path):
    traffic = Traffic("gha")
    with pytest.raises(dispatch.DispatchError):
        dispatch.dispatch_and_wait(path, request("gha"), binding("gha"), transport=traffic)
    assert traffic.calls == []


def test_ado_optional_binding_discovers_only_fixed_definition_with_pagination():
    traffic = Traffic("ado", "succeeded")
    original = traffic.request
    discovered = []
    def definition_pages(method, url, body=None, raw=False):
        if "/build/definitions?" in url:
            discovered.append(url)
            if "continuationToken=" not in url:
                return 200, {"x-ms-continuationtoken": "page 2"}, {"value": [
                    {"id": 8, "process": {"yamlFilename": "other.yml"},
                     "repository": {"url": binding("ado")["repository"]}}]}
            return 200, {}, {"value": [{"id": 9, "process": {"yamlFilename": "pipelines-only-ado.yml"},
                                       "repository": {"url": binding("ado")["repository"]}}]}
        return original(method, url, body, raw)
    traffic.request = definition_pages
    configured = binding("ado")
    del configured["pipeline_id"]
    result = dispatch.dispatch_and_wait("request.json", request("ado"), configured, transport=traffic,
                                        verify=lambda *_: {"outcome": "completed"}, correlation_id=CORRELATION)
    assert result["run_id"] == 7 and len(discovered) == 2 and "page%202" in discovered[1]


def test_rerun_during_artifact_read_is_not_reported_complete():
    traffic = Traffic("gha")
    original = traffic.request
    def rerun(method, url, body=None, raw=False):
        response = original(method, url, body, raw)
        if raw:
            traffic.rerun = True
        return response
    traffic.request = rerun
    with pytest.raises(dispatch.DispatchError, match="run-identity"):
        dispatch.dispatch_and_wait("request.json", request("gha"), binding("gha"), transport=traffic,
                                   verify=lambda *_: {"outcome": "completed"}, correlation_id=CORRELATION)


@pytest.mark.parametrize("repository", [
    "https://dev.azure.com/acme/%2e%2e/_git/factory",
    "https://dev.azure.com/acme/project%2fother/_git/factory",
    "https://dev.azure.com/acme/project/_git/%2e%2e",
])
def test_encoded_ado_routing_is_not_authorization(repository):
    with pytest.raises(dispatch.DispatchError, match="repository-invalid"):
        dispatch.validate_binding(request("ado"), dict(binding("ado"), repository=repository))


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", range(1, 7))
def test_real_transport_dispatch_wait_all_scenarios(tmp_path, monkeypatch, provider, scenario):
    from unit.test_pipeline_inputs import register, request as canonical_request, save
    monkeypatch.setenv("GH_TOKEN", "offline-token")
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "offline-token")
    traffic = Traffic(provider, "success" if provider == "gha" else "succeeded")
    save(tmp_path, register(provider))
    operational = binding(provider)
    del operational["consumer_commit"]
    (tmp_path / "provider.json").write_text(json.dumps(operational), encoding="utf-8")
    (tmp_path / "request.json").write_text(json.dumps(
        canonical_request(scenario, provider) | {"provider_binding": "provider.json"}), encoding="utf-8")
    canonical = dispatch.load_request(tmp_path, "request.json")
    if provider == "ado":
        original = traffic.run
        traffic.run = lambda: dict(original(), templateParameters={
            "correlation_id": CORRELATION, "request_digest": dispatch.digest(canonical)})
    class Response(io.BytesIO):
        def __init__(self, status, headers, body):
            super().__init__(body)
            self.status, self.headers = status, headers
    class InterceptHTTP:
        def open(self, req, timeout):
            assert req.get_header("Authorization") == "Bearer offline-token"
            body = json.loads(req.data) if req.data else None
            raw = req.full_url.endswith("/zip") or "format=zip" in req.full_url
            status, headers, value = traffic.request(req.method, req.full_url, body, raw)
            return Response(status, headers, value if raw else
                            (json.dumps(value).encode() if value is not None else b""))
    transport = dispatch.ProviderTransport(provider, dispatch.validate_binding(canonical, binding(provider)),
                                           opener=InterceptHTTP())
    verified = []
    def verify(receipt, expected):
        verified.append(expected)
        return {"outcome": "completed"}
    result = dispatch.dispatch_and_wait("request.json", canonical, binding(provider), transport=transport,
                                        verify=verify, correlation_id=CORRELATION, sleep=lambda _: None)
    assert result["outcome"] == "completed" and verified[0]["scenario"] == scenario


def test_optional_operational_binding_and_bundle_share_resolver_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, "_git", lambda *_: COMMIT)
    canonical = {"request": dict(request("gha"), azurefactory_root="azurefactory"),
                 "binding": {"repository": binding("gha")["repository"], "ref": "refs/heads/main"}}
    assert dispatch.operational_binding(tmp_path, canonical) == binding("gha")
    configured = binding("gha")
    del configured["consumer_commit"]
    with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
        archive.writestr("azurefactory/register.json", "{}")
        archive.writestr("azurefactory/provider.json", json.dumps(configured))
    canonical["request"].update(bundle="input.zip", provider_binding="azurefactory/provider.json")
    assert dispatch.operational_binding(tmp_path, canonical) == binding("gha")


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("bundled", [False, True])
def test_shipped_cold_bootstrap_binding_reaches_dispatch_without_losing_lifecycle_input(
        tmp_path, monkeypatch, capsys, provider, bundled):
    from unit.test_pipeline_inputs import register, request as canonical_request, save
    save(tmp_path, register(provider))
    configured = json.loads((ROOT / "bootstrap" / "templates" / "pipelines-only" /
                             f"{provider}-bootstrap-binding.example.json").read_text(encoding="utf-8"))
    configured["repository"] = binding(provider)["repository"]
    if provider == "ado":
        configured["pipeline_id"] = binding(provider)["pipeline_id"]
    (tmp_path / "provider.json").write_text(json.dumps(configured), encoding="utf-8")
    raw = canonical_request(1, provider) | {"provider_binding": "provider.json"}
    if bundled:
        raw["bundle"] = "input.zip"
        with zipfile.ZipFile(tmp_path / "input.zip", "w") as archive:
            for path in tmp_path.rglob("*.json"):
                archive.write(path, path.relative_to(tmp_path).as_posix())
    (tmp_path / "request.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(dispatch, "_git", lambda *_: COMMIT)
    canonical = dispatch.load_request(tmp_path, "request.json")
    original_digest = dispatch.digest(canonical)
    route = dispatch.operational_binding(tmp_path, canonical)
    assert dispatch.main(["--repo-root", str(tmp_path), "--request", "request.json", "--validate-only"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert route == binding(provider)
    assert canonical["binding"]["bootstrap"] == configured["bootstrap"]
    assert canonical["binding"]["admission"] == configured["admission"]
    assert dispatch.digest(canonical) == original_digest
    traffic = Traffic(provider, "success" if provider == "gha" else "succeeded")
    if provider == "ado":
        original_run = traffic.run
        traffic.run = lambda: dict(original_run(), templateParameters={
            "correlation_id": CORRELATION, "request_digest": dispatch.digest(canonical)})
    result = dispatch.dispatch_and_wait(
        "request.json", canonical, route, transport=traffic, correlation_id=CORRELATION,
        verify=lambda *_: {"outcome": "completed"}, sleep=lambda _: None, max_polls=2)
    assert result["outcome"] == "completed"
    assert len([call for call in traffic.calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("field,value", [
    ("bootstrap", "not-an-object"), ("admission", []), ("unknown", {}),
])
def test_dispatch_projection_does_not_hide_invalid_operational_fields(tmp_path, monkeypatch, field, value):
    from unit.test_pipeline_inputs import register, request as canonical_request, save
    save(tmp_path, register("gha"))
    configured = {key: item for key, item in binding("gha").items() if key != "consumer_commit"}
    configured[field] = value
    (tmp_path / "provider.json").write_text(json.dumps(configured), encoding="utf-8")
    (tmp_path / "request.json").write_text(json.dumps(
        canonical_request(1, "gha") | {"provider_binding": "provider.json"}), encoding="utf-8")
    monkeypatch.setattr(dispatch, "_git", lambda *_: COMMIT)
    canonical = dispatch.load_request(tmp_path, "request.json")
    with pytest.raises(dispatch.DispatchError):
        dispatch.validate_binding(canonical, dispatch.operational_binding(tmp_path, canonical))


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("mutation", ["none", "wrong-context", "wrong-plan", "nonterminal", "claim-held"])
def test_real_runtime_receipt_validation_is_authoritative(monkeypatch, provider, mutation):
    import pipeline_lifecycle
    expected = {"request_path": "request.json", "request_digest": dispatch.digest(request(provider)),
                "correlation_id": CORRELATION, "consumer_commit": COMMIT, "source_commit": SOURCE,
                "provider": provider, "repository": binding(provider)["repository"],
                "run_id": 7, "run_attempt": 1, "scenario": 1}
    operation = "11111111-1111-4111-8111-111111111111"
    receipt = {"operation_id": operation, "plan_hash": "d" * 64, "status": "succeeded",
               "provider_context": dict(expected)}
    authoritative = {"operation_id": operation, "plan_hash": "d" * 64, "status": "succeeded",
                     "plan": {"provider_context": dict(expected)}, "admission": {"status": "released"},
                     "finalization": {"status": "succeeded", "proof": {
                         "operation_id": operation, "plan_hash": "d" * 64,
                         "proof_kind": "github-rs256-native-finalizer" if provider == "gha"
                         else "ado-native-server-finalizer"}}}
    if mutation == "wrong-context":
        receipt["provider_context"]["run_id"] = 8
    elif mutation == "wrong-plan":
        receipt["plan_hash"] = "e" * 64
    elif mutation == "nonterminal":
        authoritative["status"] = "reconciliation-required"
    elif mutation == "claim-held":
        authoritative["admission"]["status"] = "held"
    class DurableService:
        def _load(self, operation_id):
            assert operation_id == operation
            return "revision", authoritative
        def observe(self, operation_id):
            raise AssertionError("Local dispatch must never observe Azure or release admission")
    real_verify = pipeline_lifecycle.verify_receipt
    monkeypatch.setattr(pipeline_lifecycle, "verify_receipt",
                        lambda value, binding, **_: real_verify(value, binding, service=DurableService()))
    traffic = Traffic(provider, "success" if provider == "gha" else "succeeded")
    original = traffic.request
    def artifact(method, url, body=None, raw=False):
        if raw:
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr("receipt.json", json.dumps(receipt))
            return 200, {}, data.getvalue()
        return original(method, url, body, raw)
    traffic.request = artifact
    if mutation == "none":
        result = dispatch.dispatch_and_wait("request.json", request(provider), binding(provider),
                                            transport=traffic, correlation_id=CORRELATION)
        assert result["outcome"] == "completed" and result["operation_id"] == operation
    else:
        with pytest.raises(ValueError):
            dispatch.dispatch_and_wait("request.json", request(provider), binding(provider),
                                       transport=traffic, correlation_id=CORRELATION)


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_provider_receipt_reader_has_no_azure_or_write_capability(provider):
    import base64
    import pipeline_lifecycle
    import provider_repository_state
    expected = {"provider": provider, "repository": binding(provider)["repository"], "consumer_commit": COMMIT}
    operation = "11111111-1111-4111-8111-111111111111"
    record = {"schema": 1, "operation_id": operation, "snapshot": {}, "snapshot_hash": dispatch.digest({}),
              "plan": {}, "prepared_at": "2026-11-12T12:00:00+00:00"}
    record["plan_hash"] = pipeline_lifecycle.digest(pipeline_lifecycle.bound_plan(record))
    state = {"schema": 1, "repository": expected["repository"], "enrollment": None, "active": None,
             "records": {"pipeline-lifecycle/" + operation + ".json": record}}
    calls = []
    class ReadOnlyHTTP:
        def request(self, method, url, body=None, raw=False):
            calls.append((method, url))
            assert method == "GET" and body is None and "management.azure.com" not in url
            if provider == "gha":
                if "/git/ref/" in url:
                    value = {"ref": provider_repository_state.STATE_REF, "object": {"type": "commit", "sha": "e" * 40}}
                elif "/git/commits/" in url:
                    value = {"tree": {"sha": "f" * 40}}
                elif "/git/trees/" in url:
                    value = {"tree": [{"path": "state.json", "type": "blob", "sha": "d" * 40}]}
                elif "/git/blobs/" in url:
                    value = {"encoding": "base64", "content": base64.b64encode(json.dumps(state).encode()).decode()}
                else:
                    value = {"private": True, "full_name": "acme/factory"}
            elif "/refs?" in url:
                value = {"value": [{"name": provider_repository_state.STATE_REF, "objectId": "e" * 40}]}
            elif "/items?" in url:
                value = {"content": json.dumps(state)}
            else:
                value = {"project": {"visibility": "private"}, "remoteUrl": expected["repository"]}
            return 200, {}, value
    reader = dispatch.ProviderReceiptReader(expected, transport=ReadOnlyHTTP())
    assert reader._load(operation)[1] == record
    count = len(calls)
    with pytest.raises(dispatch.DispatchError, match="pipeline-owned-finalizer-required"):
        reader.observe(operation)
    with pytest.raises(dispatch.DispatchError, match="read-only"):
        reader.state_request(provider, "POST", "ignored", {"write": "forbidden"})
    assert len(calls) == count
