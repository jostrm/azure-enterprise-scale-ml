import copy
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
monitoring = load_module("monitoring_report")
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text())


def test_monitoring_examples_use_canonical_sample_routes_without_jobs():
    class Client:
        def monitoring_report(self, body):
            return {"route": "report", "body": body}

        def monitoring_export(self, body):
            return {"route": "export", "body": body}

    for name, export in (("sample-report.json", False), ("sample-export.json", True)):
        body = json.loads((ROOT / "monitoring" / name).read_text())
        result = monitoring.request_report(Client(), body, export=export)
        assert result["route"] == ("export" if export else "report")
        assert result["body"] == body and body["source"] == "sample"
        assert body["filters"]["project"] == "001"


def test_monitoring_summary_example_uses_combined_route():
    class Client:
        def monitoring_summary(self, body):
            return {"route": "summary", "body": body}

    body = json.loads((ROOT / "monitoring" / "sample-summary.json").read_text())
    result = monitoring.request_report(Client(), body, summary=True)
    assert result == {"route": "summary", "body": body}
    assert body["source"] == "sample" and "report_id" not in body
    with pytest.raises(ValueError, match="CSV"):
        monitoring.request_report(Client(), body, summary=True, export=True)


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


@pytest.fixture
def configuration_example(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT.parents[1] / "azurefactory-cli" / "src"))
    editor = load_module("edit_configuration")

    class Client:
        canonical_base_url = "http://127.0.0.1:8765"
        api_key = "test-private-key"

        def __init__(self):
            self.calls = []
            self.patch = '{"region": "reviewed-private-value"}'
            self.state = {
                "aifactory_folder": r"C:\example-only\legacy\aifactory",
                "project_number_000": "001", "region": "original-private-value",
                "_json_source": {"opaque": ["source-private-value", {"preserve": True}]},
                "_future_metadata": {"unknown": ["retain", 12, False]},
            }
            self.validation = {"valid": True, "issues": []}

        def configuration_load(self, folder, project_number):
            self.calls.append(("load", folder, project_number))
            return {"state": copy.deepcopy(self.state), "warnings": []}

        def configuration_validate(self, state):
            self.calls.append(("validate", copy.deepcopy(state)))
            return copy.deepcopy(self.validation)

        def configuration_export(self, state, format="json", path=None):
            self.calls.append(("export", copy.deepcopy(state), format, path))
            return {"format": format, "content": json.dumps({"region": state["region"]}),
                    "warnings": [], "path": None}

        def configuration_save(self, state, *, write_variables=True):
            self.calls.append(("save", copy.deepcopy(state), write_variables))
            return {"snapshot_path": r"C:\example-only\snapshot.json",
                    "variables_path": r"C:\example-only\variables.json" if write_variables else None,
                    "warnings": [{"message": "Synthetic warning with " + self.api_key}],
                    "unexpected_state": copy.deepcopy(state)}

    client = Client()

    class PatchPath:
        def __init__(self, name):
            assert name == "changes.json"

        def read_text(self, *, encoding):
            assert encoding == "utf-8-sig"
            if isinstance(client.patch, Exception):
                raise client.patch
            return client.patch

    monkeypatch.setattr(editor, "Path", PatchPath)
    monkeypatch.setattr(editor, "AzureFactoryClient", lambda: client)
    args = ["--folder", client.state["aifactory_folder"], "--project-number", "001"]
    return editor, client, args


@pytest.mark.parametrize("with_patch", [False, True])
def test_configuration_example_defaults_to_private_read_only_review(configuration_example, capsys, with_patch):
    editor, client, args = configuration_example
    if with_patch:
        args += ["--changes-json", "changes.json"]
    assert editor.main(args) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["changed_fields"] == (["region"] if with_patch else [])
    assert result["can_save"] is True
    assert len(result["review_id"]) == 64
    assert [call[0] for call in client.calls] == ["load", "validate", "export"]
    assert client.calls[0][1:] == (args[1], "001")
    assert client.calls[-1][2:] == ("json", None)
    assert "private-value" not in output.out + output.err
    assert "_json_source" not in output.out + output.err
    assert "_future_metadata" not in output.out + output.err


@pytest.mark.parametrize("snapshot_only", [False, True])
def test_configuration_example_saves_only_separately_reviewed_full_state(configuration_example, capsys, snapshot_only):
    editor, client, args = configuration_example
    original = copy.deepcopy(client.state)
    args += ["--changes-json", "changes.json"]
    if snapshot_only:
        args += ["--snapshot-only"]
    assert editor.main(args) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["write_variables"] is not snapshot_only
    assert editor.main([*args, "--save", "--expected-review", review["review_id"], "--yes"]) == 0
    output = capsys.readouterr()
    saved = json.loads(output.out)
    assert set(saved) == {"snapshot_path", "variables_path", "warnings"}
    assert [call[0] for call in client.calls] == [
        "load", "validate", "export", "load", "validate", "export", "save",
    ]
    assert client.calls[-1][1] == {**original, "region": "reviewed-private-value"}
    assert client.calls[-1][2] is not snapshot_only
    assert client.state == original
    assert "private-value" not in output.out + output.err
    assert "_json_source" not in output.out + output.err
    assert client.api_key not in output.out + output.err


@pytest.mark.parametrize("flags", [
    ["--save"], ["--save", "--yes"], ["--save", "--expected-review", "a" * 64],
    ["--yes"], ["--expected-review", "a" * 64],
])
def test_configuration_example_rejects_missing_or_misplaced_approval(configuration_example, flags):
    editor, client, args = configuration_example
    assert editor.main([*args, *flags]) == 2
    assert not client.calls


@pytest.mark.parametrize("changed_input", ["patch", "source", "write_choice", "host"])
def test_configuration_example_requires_same_review(configuration_example, capsys, changed_input):
    editor, client, args = configuration_example
    args += ["--changes-json", "changes.json"]
    assert editor.main(args) == 0
    review_id = json.loads(capsys.readouterr().out)["review_id"]
    if changed_input == "patch":
        client.patch = '{"region":"different-value"}'
    elif changed_input == "source":
        client.state["_future_metadata"]["unknown"].append("changed")
    elif changed_input == "write_choice":
        args += ["--snapshot-only"]
    else:
        client.canonical_base_url = "http://127.0.0.1:8766"
    assert editor.main([*args, "--save", "--expected-review", review_id, "--yes"]) == 3
    assert not any(call[0] == "save" for call in client.calls)


def test_configuration_example_blocks_invalid_review(configuration_example, capsys):
    editor, client, args = configuration_example
    client.validation = {"valid": False, "issues": [{"severity": "error", "message": "Invalid field."}]}
    assert editor.main(args) == 3
    assert json.loads(capsys.readouterr().out)["can_save"] is False
    assert [call[0] for call in client.calls] == ["load", "validate"]


def test_configuration_example_requires_persistent_json_source(configuration_example):
    editor, client, args = configuration_example
    del client.state["_json_source"]
    assert editor.main(args) == 3
    assert [call[0] for call in client.calls] == ["load"]


@pytest.mark.parametrize("patch", [
    '{"_json_source":{}}', '{"_future_metadata":{}}',
    '{"project_number_000":"002"}', '{"unknown_field":"value"}',
])
def test_configuration_example_blocks_identity_private_and_unknown_edits(configuration_example, patch):
    editor, client, args = configuration_example
    client.patch = patch
    assert editor.main([*args, "--changes-json", "changes.json"]) == 2
    assert [call[0] for call in client.calls] == ["load"]


@pytest.mark.parametrize("patch", [
    "null", "[]", '{"region": NaN}', "{broken-private-value",
    FileNotFoundError("missing-private-value"), PermissionError("denied-private-value"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid-private-value"),
])
def test_configuration_example_surfaces_patch_errors_without_contents(configuration_example, capsys, patch):
    editor, client, args = configuration_example
    client.patch = patch
    assert editor.main([*args, "--changes-json", "changes.json"]) == 2
    assert "private-value" not in capsys.readouterr().err
    assert not client.calls


@pytest.mark.parametrize("error_name,code", [
    ("APIError", 1), ("ConfigError", 2), ("BlockedError", 3),
    ("RequestTimeout", 4), ("FailureError", 5), ("AuthError", 6),
])
def test_configuration_example_preserves_sdk_errors_without_logging_payloads(
    configuration_example, monkeypatch, capsys, error_name, code,
):
    import azurefactory

    editor, client, args = configuration_example
    attempts = []

    def fail_load(*args):
        attempts.append(args)
        raise getattr(azurefactory, error_name)(
            "sensitive-private-value", status=409, details={"state": client.state},
        )

    monkeypatch.setattr(client, "configuration_load", fail_load)
    assert editor.main(args) == code
    output = capsys.readouterr()
    assert len(attempts) == 1
    assert "409" in output.err
    assert "private-value" not in output.out + output.err
    assert "_json_source" not in output.out + output.err


def test_configuration_example_does_not_retry_ambiguous_save(configuration_example, monkeypatch, capsys):
    editor, client, args = configuration_example
    assert editor.main(args) == 0
    review_id = json.loads(capsys.readouterr().out)["review_id"]
    attempts = []

    def ambiguous_save(state, *, write_variables):
        attempts.append((state, write_variables))
        raise editor.APIError("Ambiguous response with private-value", details={"state": state})

    monkeypatch.setattr(client, "configuration_save", ambiguous_save)
    assert editor.main([*args, "--save", "--expected-review", review_id, "--yes"]) == 1
    assert len(attempts) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "do not blindly retry a save" in output.err
    assert "private-value" not in output.err


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
