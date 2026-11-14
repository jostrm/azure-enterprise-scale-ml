"""Provider artifact ZIP transport into the same virtual canonical resolver."""
import copy
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
from urllib.parse import parse_qs, urlsplit
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_dispatch as dispatch
from unit.test_pipeline_inputs import register, request, VARIABLES


CONSUMER = "b" * 40
PRODUCER = "e" * 40


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live artifact traffic forbidden"))


def repository(provider):
    return ("https://github.com/acme/factory" if provider == "gha"
            else "https://dev.azure.com/acme/project/_git/factory")


def fixture(root, provider):
    document = register(provider)
    factory_id = document["factories"][0]["id"]
    project_id = document["factories"][0]["projects"][0]["id"]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("azurefactory/register.json", json.dumps(document))
        bundle.writestr(VARIABLES, json.dumps(document["configurations"][factory_id]["variables"][project_id]))
        bundle.writestr("azurefactory/provider.json", json.dumps({
            "schema": 1, "provider": provider, "repository": repository(provider)}))
    inner = archive.getvalue()
    raw = request(provider=provider) | {"bundle": ".inputs/registered.zip",
                                        "provider_binding": "azurefactory/provider.json"}
    source = {"schema": 1, "provider": provider, "repository": repository(provider),
              "run_id": 123, "artifact_name": "esaf-inputs", "archive_path": "registered.zip",
              "archive_sha256": hashlib.sha256(inner).hexdigest(), "producer_commit": PRODUCER}
    (root / "request.json").write_text(json.dumps(raw))
    (root / "request.json.artifact.json").write_text(json.dumps(source))
    return raw, source, inner


def fake_git(root, *arguments):
    if arguments == ("rev-parse", "HEAD"):
        return "a" * 40 if Path(root).name == "azure-enterprise-scale-ml" else CONSUMER
    if arguments[:1] == ("ls-tree",):
        return "160000 commit " + "a" * 40 + "\tazure-enterprise-scale-ml"
    if arguments[:1] == ("ls-files",):
        return arguments[-1]
    if arguments[:1] == ("status",):
        return ""
    raise AssertionError(arguments)


def environment(provider):
    if provider == "gha":
        return {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "acme/factory",
                "GITHUB_SHA": CONSUMER, "GITHUB_WORKFLOW_SHA": CONSUMER, "GITHUB_RUN_ATTEMPT": "1"}
    return {"TF_BUILD": "True", "BUILD_REPOSITORY_URI": repository(provider),
            "BUILD_SOURCEVERSION": CONSUMER, "SYSTEM_JOBATTEMPT": "1"}


class Artifacts:
    def __init__(self, provider, source, inner):
        self.provider, self.source, self.inner = provider, source, inner
        self.calls, self.status, self.attempt = [], "success" if provider == "gha" else "succeeded", 1
        self.wrapper_path = "registered.zip" if provider == "gha" else "esaf-inputs/registered.zip"
        self.extra = None
        self.download_url = "https://dev.azure.com/acme/project/_apis/build/builds/123/artifacts?format=zip"

    def request(self, method, url, body=None, raw=False):
        assert method == "GET" and body is None
        self.calls.append(url)
        if raw:
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as outer:
                outer.writestr(self.wrapper_path, self.inner)
                if self.extra:
                    outer.writestr(self.extra, b"unreviewed")
            return 200, {}, data.getvalue()
        if "/artifacts" in url:
            if self.provider == "gha":
                return 200, {}, {"artifacts": [{
                    "id": 44, "name": self.source["artifact_name"], "expired": False,
                    "workflow_run": {"id": 123, "head_sha": PRODUCER}}]}
            return 200, {}, {"value": [{"name": self.source["artifact_name"], "resource": {
                "downloadUrl": self.download_url}}]}
        if self.provider == "gha":
            return 200, {}, {"id": 123, "head_sha": PRODUCER, "run_attempt": self.attempt,
                             "repository": {"full_name": "acme/factory"}, "status": "completed",
                             "conclusion": self.status}
        return 200, {}, {"id": 123, "sourceVersion": PRODUCER, "status": "completed",
                         "repository": {"url": repository("ado")}, "result": self.status}


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_download_exact_artifact_to_virtual_bundle_then_resolve(tmp_path, monkeypatch, provider):
    raw, source, inner = fixture(tmp_path, provider)
    monkeypatch.setattr(dispatch, "_git", fake_git)
    transport = Artifacts(provider, source, inner)
    result = dispatch.download_input(tmp_path, "request.json", provider=provider,
                                     transport=transport, environ=environment(provider))
    assert result["downloaded"] is True
    assert (tmp_path / raw["bundle"]).read_bytes() == inner
    canonical = dispatch.load_request(tmp_path, "request.json")
    assert canonical["request"]["scenario"] == 3 and canonical["factory"]["key"] == "acme-ai"
    assert not (tmp_path / "azurefactory").exists(), "The JSON bundle must never be extracted"
    dispatch.download_input(tmp_path, "request.json", provider=provider,
                             transport=transport, environ=environment(provider))
    assert (tmp_path / raw["bundle"]).read_bytes() == inner


@pytest.mark.parametrize("download_url", [
    "https://dev.azure.com/acme/project/_apis/build/builds/123/artifacts?format=zip",
    "https://dev.azure.com/acme/11111111-2222-4333-8444-555555555555/_apis/build/builds/123/artifacts?format=zip",
    "https://dev.azure.com/acme/other-project/_apis/build/builds/123/artifacts?format=zip",
    "https://dev.azure.com/other-org/project/_apis/build/builds/123/artifacts?format=zip",
    "https://attacker.invalid/acme/project/_apis/build/builds/123/artifacts?format=zip",
    "https://dev.azure.com/acme/project/_apis/build/builds/999/artifacts?artifactName=other&format=zip",
])
def test_ado_input_content_uses_verified_route_not_metadata_url(tmp_path, monkeypatch, download_url):
    raw, source, inner = fixture(tmp_path, "ado")
    monkeypatch.setattr(dispatch, "_git", fake_git)
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "offline-token")
    traffic = Artifacts("ado", source, inner)
    traffic.download_url = download_url
    base = dispatch.validate_binding(raw, {"schema": 1, "provider": "ado", "consumer_commit": CONSUMER,
                                          "repository": repository("ado")})
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
            binary = query.get("$format") == ["zip"] or query.get("format") == ["zip"]
            if binary:
                assert req.full_url.split("?", 1)[0] == base + "/build/builds/123/artifacts"
                assert query == {"artifactName": ["esaf-inputs"], "$format": ["zip"], "api-version": ["7.1"]}
                downloads.append(req.full_url)
            status, headers, value = traffic.request(req.method, req.full_url, raw=binary)
            return Response(status, headers, value if binary else json.dumps(value).encode())

    transport = dispatch.ProviderTransport("ado", base, opener=InterceptHTTP())
    result = dispatch.download_input(tmp_path, "request.json", provider="ado",
                                     transport=transport, environ=environment("ado"))
    assert result["downloaded"] is True and (tmp_path / raw["bundle"]).read_bytes() == inner
    assert len(downloads) == 1 and downloads[0] != download_url


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("change", ["wrong-repository", "failed", "traversal", "extra-file"])
def test_untrusted_or_failed_input_artifact_never_reaches_resolver(tmp_path, monkeypatch, provider, change):
    raw, source, inner = fixture(tmp_path, provider)
    monkeypatch.setattr(dispatch, "_git", fake_git)
    transport = Artifacts(provider, source, inner)
    if change == "wrong-repository":
        source["repository"] += "-other"
        (tmp_path / "request.json.artifact.json").write_text(json.dumps(source))
    elif change == "failed":
        transport.status = "failure" if provider == "gha" else "failed"
    elif change == "traversal":
        transport.wrapper_path = "../registered.zip"
    else:
        transport.extra = "another.zip"
    with pytest.raises((dispatch.DispatchError, ValueError)):
        dispatch.download_input(tmp_path, "request.json", provider=provider,
                                 transport=transport, environ=environment(provider))
    assert not (tmp_path / raw["bundle"]).exists()
    if change == "wrong-repository":
        assert transport.calls == []


def test_input_artifact_rerun_is_rejected(tmp_path, monkeypatch):
    raw, source, inner = fixture(tmp_path, "gha")
    monkeypatch.setattr(dispatch, "_git", fake_git)
    transport = Artifacts("gha", source, inner)
    transport.attempt = 2
    with pytest.raises(dispatch.DispatchError):
        dispatch.download_input(tmp_path, "request.json", provider="gha",
                                 transport=transport, environ=environment("gha"))
    assert not (tmp_path / raw["bundle"]).exists()


def test_existing_bundle_is_never_overwritten(tmp_path, monkeypatch):
    raw, source, inner = fixture(tmp_path, "gha")
    monkeypatch.setattr(dispatch, "_git", fake_git)
    target = tmp_path / raw["bundle"]
    target.parent.mkdir()
    target.write_bytes(b"existing-user-file")
    with pytest.raises(dispatch.DispatchError, match="existing-bundle"):
        dispatch.download_input(tmp_path, "request.json", provider="gha",
                                 transport=Artifacts("gha", source, inner), environ=environment("gha"))
    assert target.read_bytes() == b"existing-user-file"


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_source_archive_hint_drift_is_review_evidence_not_authority(tmp_path, monkeypatch, provider):
    raw, source, inner = fixture(tmp_path, provider)
    source["archive_sha256"] = "0" * 64
    (tmp_path / "request.json.artifact.json").write_text(json.dumps(source))
    monkeypatch.setattr(dispatch, "_git", fake_git)
    for _ in range(2):
        result = dispatch.download_input(tmp_path, "request.json", provider=provider,
                                         transport=Artifacts(provider, source, inner),
                                         environ=environment(provider))
        assert result["input_artifact"]["drift"] is True
        assert result["input_artifact"]["warning"] == "input-archive-digest-drift"
        assert result["archive_sha256"] == hashlib.sha256(inner).hexdigest()
        assert result["input_artifact"] == dispatch.input_evidence(tmp_path, "request.json")
    assert (tmp_path / raw["bundle"]).read_bytes() == inner


def test_no_bundle_has_no_provider_reads(tmp_path):
    (tmp_path / "request.json").write_text(json.dumps(request()))
    assert dispatch.download_input(tmp_path, "request.json") == {"downloaded": False}


@pytest.mark.parametrize("target", [".git/input.zip", ".esaf/context.zip",
                                   "azure-enterprise-scale-ml/input.zip", "sitecustomize.py"])
def test_bundle_cannot_write_source_or_internal_state(tmp_path, monkeypatch, target):
    raw, source, inner = fixture(tmp_path, "gha")
    raw["bundle"] = target
    (tmp_path / "request.json").write_text(json.dumps(raw))
    monkeypatch.setattr(dispatch, "_git", fake_git)
    transport = Artifacts("gha", source, inner)
    with pytest.raises(dispatch.DispatchError, match="safe-input-bundle-target"):
        dispatch.download_input(tmp_path, "request.json", provider="gha",
                                 transport=transport, environ=environment("gha"))
    assert transport.calls == []


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_invalid_virtual_bundle_is_removed_not_extracted(tmp_path, monkeypatch, provider):
    raw, source, inner = fixture(tmp_path, provider)
    source["archive_sha256"] = hashlib.sha256(b"not-a-zip").hexdigest()
    (tmp_path / "request.json.artifact.json").write_text(json.dumps(source))
    monkeypatch.setattr(dispatch, "_git", fake_git)
    with pytest.raises(ValueError):
        dispatch.download_input(tmp_path, "request.json", provider=provider,
                                 transport=Artifacts(provider, source, b"not-a-zip"),
                                 environ=environment(provider))
    assert not (tmp_path / raw["bundle"]).exists()
    assert not (tmp_path / "azurefactory").exists()


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("name", [".env", ".env.local", "azurefactory/.env.json", "azurefactory/private.env"])
def test_environment_files_are_never_accepted_as_pipeline_artifacts(tmp_path, monkeypatch, provider, name):
    raw, source, inner = fixture(tmp_path, provider)
    monkeypatch.setattr(dispatch, "_git", fake_git)
    content = io.BytesIO(inner)
    with zipfile.ZipFile(content, "a") as archive:
        archive.writestr(name, '{"innocent": "must-not-be-uploaded"}')
    with pytest.raises(dispatch.DispatchError, match="environment-file-transport-forbidden"):
        dispatch.download_input(tmp_path, "request.json", provider=provider,
                                 transport=Artifacts(provider, source, content.getvalue()),
                                 environ=environment(provider))
    assert not (tmp_path / raw["bundle"]).exists()
