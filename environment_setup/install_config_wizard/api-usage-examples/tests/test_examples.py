import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "python" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = load_module("render_request")
patcher = load_module("parameter_patch")
inspector = load_module("inspect_factory")
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text())


def example_environment():
    result = {
        "FACTORY_FOLDER": r"C:\factory-examples\azurefactory",
        "LEGACY_FACTORY_FOLDER": r"C:\factory-examples\legacy\aifactory",
        "NEW_REPO_ROOT": r"C:\factory-examples\new-bootstrap",
        "CATALOG_REVISION": "a" * 64,
        "GITHUB_REPOSITORY": "example-org/new-factory",
        "TEAM_MEMBER_EMAIL": "platform@example.com",
        "TEAM_GROUP_NAME": "central-cloud",
        "COST_CENTER": "CC123",
        "ADO_ORGANIZATION": "https://dev.azure.com/example-org",
        "ADO_PROJECT": "Platform",
        "ADO_REPOSITORY": "new-factory",
        "ADO_SERVICE_CONNECTION": "factory-oidc",
    }
    for number, key in enumerate((
        "DEV_SUBSCRIPTION_ID", "TENANT_ID", "FACTORY_ID", "DEV_SCALESET_001_ID",
        "DEV_SCALESET_002_ID", "STAGE_SUBSCRIPTION_ID", "PROJECT_ID",
        "STAGE_SCALESET_001_ID", "CONFIRMATION_ID", "DRAFT_ID",
    ), start=1):
        result[key] = f"00000000-0000-4000-8000-{number:012d}"
    return result


@pytest.mark.parametrize("filename", SCENARIOS)
def test_templates_render_as_typed_json(filename):
    body = renderer.render(json.loads((ROOT / "requests" / filename).read_text()), example_environment())
    assert "${" not in json.dumps(body)
    if "contract_version" in body:
        assert type(body["contract_version"]) is int
    if "patch" in body:
        assert body["patch"] is False


def test_manifest_covers_every_template():
    assert set(SCENARIOS) == {path.name for path in (ROOT / "requests").glob("*.json")}


def test_renderer_preserves_escaping_and_types():
    value = r'C:\A & B\"quoted"\folder'
    assert renderer.render({"folder": "${FOLDER}", "flag": False}, {"FOLDER": value}) == {
        "folder": value, "flag": False,
    }


@pytest.mark.parametrize("value", ["${MISSING}", "${lowercase}", "${BROKEN"])
def test_renderer_rejects_unresolved_values(value):
    with pytest.raises(ValueError):
        renderer.render({"value": value}, {})


def test_renderer_refuses_overwrite(tmp_path):
    output = tmp_path / "request.json"
    output.write_text("unchanged")
    result = subprocess.run(
        [sys.executable, str(ROOT / "python" / "render_request.py"),
         str(ROOT / "requests" / "01-create-factory.json"), "--out", str(output)],
        env={**os.environ, **example_environment()}, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert output.read_text() == "unchanged"


def snapshot():
    return {
        "contract_version": 1, "requires_profile_reset": False,
        "factory_id": example_environment()["FACTORY_ID"],
        "scale_set_id": example_environment()["DEV_SCALESET_001_ID"],
        "project_id": example_environment()["PROJECT_ID"],
        "source_revision": "a" * 64, "schema_revision": "b" * 64,
        "templates": [{
            "template": "published-template",
            "fields": [{"name": "enabled", "sensitive": False}],
            "parameter_schema": {"properties": {"enabled": {"type": "boolean"}}},
        }],
    }


def test_parameter_patch_preserves_scope_revision_and_native_boolean():
    result = patcher.build_patch(snapshot(), "folder", "published-template", "enabled", True)
    assert result["expected_revision"] == "a" * 64
    assert result["schema_revision"] == "b" * 64
    assert result["reset_profile"] is False
    assert result["templates"] == [{"template": "published-template", "parameters": {"enabled": True}}]


@pytest.mark.parametrize("issue", ["reset", "secret", "unknown", "readonly", "contract"])
def test_parameter_patch_refuses_unsafe_edits(issue):
    document = snapshot()
    parameter = "enabled"
    if issue == "reset":
        document["requires_profile_reset"] = True
    elif issue == "secret":
        document["templates"][0]["fields"][0]["sensitive"] = True
    elif issue == "unknown":
        parameter = "guessedParameter"
    elif issue == "readonly":
        document["templates"][0]["parameter_schema"]["properties"]["enabled"]["readOnly"] = True
    else:
        document["contract_version"] = 9
    with pytest.raises(ValueError):
        patcher.build_patch(document, "folder", "published-template", parameter, True)


@pytest.fixture
def server():
    calls = []
    response = {"code": 200, "body": {"status": "ok"}}

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.path, dict(self.headers), json.loads(body) if body else None))
            self.send_response(response["code"])
            self.send_header("Content-Type", "application/json")
            if response["code"] == 302:
                self.send_header("Location", "/api/v1/redirect-target")
            self.end_headers()
            self.wfile.write(json.dumps(response["body"]).encode())

        do_GET = handle_request
        do_POST = handle_request

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls, response
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


def invoke(consumer, base, path, extra=(), environment=None):
    executable = shutil.which("node" if consumer == "node" else "pwsh")
    if not executable:
        pytest.skip(f"{consumer} is not installed")
    if consumer == "node":
        command = [executable, str(ROOT / "node" / "request.mjs"), "--base", base, "--path", path]
    else:
        command = [executable, "-NoProfile", "-File", str(ROOT / "powershell" / "Request-AzureFactory.ps1"),
                   "-BaseUrl", base, "-Path", path]
    env = {**os.environ, "AIFACTORY_API_KEY": "test-private-key", **(environment or {})}
    return subprocess.run([*command, *extra], capture_output=True, text=True, env=env, timeout=20)


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_health_without_sending_key(consumer, server):
    base, calls, _ = server
    result = invoke(consumer, base, "/health")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ok"
    assert "X-API-Key" not in calls[0][1]


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_post_exact_json_and_auth(consumer, server, tmp_path):
    base, calls, response = server
    body = {"folder": r"C:\folder with spaces", "contract_version": 1}
    body_file = tmp_path / "payload.json"
    body_file.write_text(json.dumps(body))
    response["body"] = {"can_execute": False, "blockers": ["review binding"]}
    flags = (["--method", "POST", "--body", str(body_file), "--allow-write"] if consumer == "node"
             else ["-Method", "POST", "-BodyFile", str(body_file), "-AllowWrite"])
    result = invoke(consumer, base, "/api/v1/factory-catalog/prepare", flags)
    assert result.returncode == 3, result.stderr
    assert calls[0][2] == body
    assert calls[0][1]["X-API-Key"] == "test-private-key"


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_write_guard(consumer, server):
    base, calls, _ = server
    flags = ["--method", "POST"] if consumer == "node" else ["-Method", "POST"]
    result = invoke(consumer, base, "/api/v1/factory-catalog/confirm", flags)
    assert result.returncode == 2
    assert not calls


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_reject_redirects(consumer, server):
    base, calls, response = server
    response["code"] = 302
    result = invoke(consumer, base, "/api/v1/schema")
    assert result.returncode == 2
    assert len(calls) == 1


@pytest.mark.parametrize("consumer", ["node", "powershell"])
@pytest.mark.parametrize("path", ["//example.com/api/v1/schema", "/api/v1/../schema", "/health?key=secret"])
def test_raw_clients_reject_unsafe_paths(consumer, server, path):
    base, calls, _ = server
    assert invoke(consumer, base, path).returncode == 2
    assert not calls


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_redact_error_and_fail_job(consumer, server):
    base, calls, response = server
    response.update(code=401, body={"detail": "test-private-key"})
    result = invoke(consumer, base, "/api/v1/schema")
    assert result.returncode == 2
    assert "test-private-key" not in result.stderr + result.stdout
    assert "401" in result.stderr
    response.update(code=200, body={"status": "failed"})
    assert invoke(consumer, base, "/health").returncode == 4


def test_node_query_values_are_encoded(server):
    base, calls, _ = server
    folder = r"C:\folder & spaces\aifactory"
    result = invoke("node", base, "/api/v1/factory-catalog", ["--query", "folder=" + folder])
    assert result.returncode == 0, result.stderr
    assert parse_qs(urlsplit(calls[0][0]).query) == {"folder": [folder]}


def test_powershell_query_values_are_encoded(server):
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell is not installed")
    base, calls, _ = server
    folder = r"C:\folder & spaces\aifactory"
    script = ROOT / "powershell" / "Request-AzureFactory.ps1"
    command = "& '{}' -BaseUrl '{}' -Path /api/v1/factory-catalog -Query @{{folder=$env:TEST_QUERY_FOLDER}}".format(
        str(script).replace("'", "''"), base,
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=20,
        env={**os.environ, "AIFACTORY_API_KEY": "test-private-key", "TEST_QUERY_FOLDER": folder},
    )
    assert result.returncode == 0, result.stderr
    assert parse_qs(urlsplit(calls[0][0]).query) == {"folder": [folder]}


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_missing_key_fails_before_request(consumer, server):
    base, calls, _ = server
    result = invoke(consumer, base, "/api/v1/schema", environment={"AIFACTORY_API_KEY": ""})
    assert result.returncode == 2
    assert not calls


@pytest.mark.parametrize("consumer", ["node", "powershell"])
def test_raw_clients_reject_unrendered_templates(consumer, server):
    base, calls, _ = server
    template = str(ROOT / "requests" / "01-create-factory.json")
    flags = (["--method", "POST", "--body", template, "--allow-write"] if consumer == "node"
             else ["-Method", "POST", "-BodyFile", template, "-AllowWrite"])
    assert invoke(consumer, base, "/api/v1/factory-catalog/prepare", flags).returncode == 2
    assert not calls


@pytest.mark.parametrize("consumer", ["node", "powershell"])
@pytest.mark.parametrize("base", ["http://[::10]:8765", "https://example.com", "http://127.0.0.1:8765/private"])
def test_raw_clients_reject_nonlocal_or_nonorigin_base(consumer, base):
    assert invoke(consumer, base, "/health").returncode == 2


@pytest.mark.parametrize("document", [[], None, {"contract_version": True}])
def test_parameter_patch_rejects_malformed_response(document):
    with pytest.raises(ValueError):
        patcher.build_patch(document, "folder", "template", "field", True)


def test_sdk_example_selects_exact_scope_without_writes():
    calls = []

    class Client:
        def catalog_list(self, folder):
            return {
                "contract_version": 1, "mode": "catalog", "revision": "current",
                "factories": [{
                    "id": "f", "key": "chosen", "scale_sets": [
                        {"id": "s-dev", "environment": "dev", "suffix": "001", "tenant_id": "t", "subscription_id": "sub-dev"},
                        {"id": "s-stage", "environment": "stage", "suffix": "001", "tenant_id": "t", "subscription_id": "sub-stage"},
                    ],
                    "projects": [{"id": "p", "number": "001", "placements": [
                        {"environment": "stage", "scale_set_id": "s-stage"},
                    ]}],
                }],
            }

        def auth_status(self, **kwargs):
            calls.append(("auth", kwargs))
            return {"status": "checked"}

        def catalog_parameters(self, *args):
            calls.append(("parameters", args))
            return {"templates": []}

    result = inspector.inspect_factory(Client(), "folder", "chosen", "stage", "001", "001",
                                       parameters=True, auth_status=True)
    assert result["scale_set_id"] == "s-stage"
    assert result["project_id"] == "p"
    assert calls == [
        ("auth", {"aifactory_folder": "folder", "factory_id": "f", "scale_set_id": "s-stage",
                  "expected_tenant_id": "t", "expected_subscription_id": "sub-stage"}),
        ("parameters", ("folder", "f", "s-stage", "p")),
    ]
    with pytest.raises(ValueError, match="project placement"):
        inspector.inspect_factory(Client(), "folder", "chosen", "dev", "001", "001")
    with pytest.raises(ValueError, match="factory key"):
        inspector.inspect_factory(Client(), "folder", "missing", "dev", "001")
    with pytest.raises(ValueError, match="scale-set suffix"):
        inspector.inspect_factory(Client(), "folder", "chosen", "stage", "002")


def test_sdk_example_rejects_ambiguous_selection():
    with pytest.raises(ValueError, match="found 2"):
        inspector.exactly_one([{"id": "a"}, {"id": "b"}], "factory")


@pytest.mark.skipif(not os.environ.get("AIFACTORY_API_SOURCE"), reason="Optional master-source contract validation")
@pytest.mark.parametrize("filename,scenario", SCENARIOS.items())
def test_templates_against_canonical_request_models(filename, scenario, monkeypatch):
    monkeypatch.syspath_prepend(os.environ["AIFACTORY_API_SOURCE"])
    from src import api, creation

    body = renderer.render(json.loads((ROOT / "requests" / filename).read_text()), example_environment())
    model = creation.BootstrapPrepare if scenario["model"] == "BootstrapPrepare" else getattr(api, scenario["model"])
    model.model_validate(body)
    route = api.app.openapi()["paths"][scenario["path"]]["post"]
    assert route["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/" + scenario["model"])
