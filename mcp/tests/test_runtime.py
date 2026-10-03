import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


ROOT = Path(__file__).resolve().parents[2]
MCP = ROOT / "mcp"
AGENT = ROOT / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"
SDK = ROOT / "environment_setup" / "azurefactory-cli" / "src"
for source in (SDK, AGENT):
    sys.path.insert(0, str(source))


def load_fixture_module(name):
    spec = importlib.util.spec_from_file_location(name, AGENT / "tests" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


security_fixtures = load_fixture_module("test_security")
action_fixtures = load_fixture_module("test_actions")
CALLER = security_fixtures.CALLER
SCOPE = security_fixtures.SCOPE


@pytest.fixture
def configuration():
    values = security_fixtures.settings.__wrapped__().model_dump(mode="json")
    values["knowledge"]["repository_root"] = str(ROOT)
    values["auth"]["grants"][0]["permissions"] += [
        "factory.create", "factory.delete", "project.add", "cost.read",
    ]
    values["actions"] = {
        "enabled_skills": list(action_fixtures.ACTION_SKILLS),
        "bootstrap_profiles": {SCOPE: action_fixtures.profile_values()},
        "deletion_resource_groups": {SCOPE: [action_fixtures.GROUP]},
    }
    values["factory"]["operation_signing_secret_url"] = "https://example.vault.azure.net/secrets/operations"
    return values


@pytest.fixture
def artifacts():
    path = MCP / ".test-state" / str(uuid4())
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


@pytest.fixture
def config_path(configuration, artifacts):
    path = artifacts / "agent.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    return path


@pytest.fixture
def runtime(config_path):
    from aifactory_mcp.runtime import load_runtime

    return load_runtime(config_path, repository_root=ROOT)


def test_runtime_loads_real_agent_and_sdk(runtime):
    from aifactory_agent.config import Settings
    from aifactory_agent.security import Principal
    from aifactory_mcp.backend import AgentBackend
    import azurefactory.client

    assert isinstance(runtime.settings, Settings)
    caller = runtime.local_principal(CALLER)
    assert isinstance(caller, Principal)
    assert caller.tenant_id == security_fixtures.TENANT
    assert isinstance(runtime.backend(caller, SCOPE), AgentBackend)
    assert Path(azurefactory.client.__file__).resolve().is_relative_to(SDK)


def test_repository_discovery_from_source_checkout(config_path):
    from aifactory_mcp.runtime import load_runtime

    assert load_runtime(config_path).settings.tenant_id == security_fixtures.TENANT


def test_explicit_repository_must_contain_actual_sources(config_path, artifacts):
    from aifactory_mcp.runtime import load_runtime

    with pytest.raises(RuntimeError, match="repository"):
        load_runtime(config_path, artifacts)


@pytest.mark.parametrize("identity", ["", "caller@example.test", "not-a-uuid", "00000000-0000-0000-0000-000000000000", None])
def test_local_identity_is_explicit_nonzero_uuid(runtime, identity):
    with pytest.raises((ValueError, PermissionError)):
        runtime.local_principal(identity)


def test_runtime_never_uses_environment_bearer_identity(runtime, monkeypatch):
    monkeypatch.setenv("AIFACTORY_TOKEN", "not-a-trusted-token")
    monkeypatch.setenv("AZURE_ACCESS_TOKEN", "not-a-trusted-token")
    monkeypatch.setattr("aifactory_agent.security._jwks_client", lambda _: pytest.fail("local identity used network"))
    assert runtime.local_principal(CALLER).object_id == CALLER


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_token_verification_uses_signature_audience_and_tenant(runtime, signing_key, monkeypatch):
    urls = []

    def keys(url):
        urls.append(url)
        return SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=signing_key.public_key()))

    monkeypatch.setattr("aifactory_agent.security._jwks_client", keys)
    valid = jwt.encode(security_fixtures.claims(), signing_key, algorithm="RS256")
    assert runtime.principal_from_token(valid).object_id == CALLER
    assert urls == [f"https://login.microsoftonline.com/{security_fixtures.TENANT}/discovery/v2.0/keys"]
    for changes in ({"aud": "other"}, {"tid": security_fixtures.CLIENT}, {"exp": 1}, {"scp": "wrong"}):
        token = jwt.encode(security_fixtures.claims(**changes), signing_key, algorithm="RS256")
        with pytest.raises(PermissionError):
            runtime.principal_from_token(token)
    with pytest.raises(PermissionError):
        runtime.principal_from_token(jwt.encode(security_fixtures.claims(), "", algorithm="none"))


def test_unconfigured_network_audience_fails_closed(runtime):
    from dataclasses import replace

    settings = runtime.settings.model_copy(update={"auth": runtime.settings.auth.model_copy(update={"audience": None})})
    with pytest.raises(RuntimeError):
        replace(runtime, settings=settings).principal_from_token("irrelevant")


def test_invalid_settings_error_does_not_echo_config_secret(config_path):
    from aifactory_mcp.runtime import load_runtime

    config_path.write_text('{"password":"configuration-secret"}', encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        load_runtime(config_path, ROOT)
    assert "configuration-secret" not in str(exc.value)


def test_package_outside_checkout_requires_explicit_repository(config_path, monkeypatch):
    import aifactory_mcp.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "__file__", str(Path("Z:\\not-a-checkout\\aifactory_mcp\\runtime.py")))
    with pytest.raises(RuntimeError, match="repository_root"):
        runtime_module.load_runtime(config_path)
    assert runtime_module.load_runtime(config_path, ROOT).settings.tenant_id == security_fixtures.TENANT


def test_runtime_rejects_untrusted_preloaded_modules(config_path, monkeypatch):
    from aifactory_mcp.runtime import load_runtime

    monkeypatch.setitem(sys.modules, "aifactory_agent.untrusted", SimpleNamespace(__file__=str(MCP / "untrusted.py")))
    with pytest.raises(RuntimeError, match="outside"):
        load_runtime(config_path, ROOT)


def test_cli_health_works_with_only_installed_mcp_import_path(configuration, config_path):
    import os
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/health"
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        configuration["factory"]["api_url"] = f"http://127.0.0.1:{server.server_port}"
        config_path.write_text(json.dumps(configuration), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(MCP / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        script = (
            "import json,sys; from aifactory_mcp.runtime import load_runtime; "
            "r=load_runtime(sys.argv[1],sys.argv[2]); "
            f"b=r.backend(r.local_principal('{CALLER}'),'{SCOPE}'); "
            "print(json.dumps(b.call_tool('factory_cli_health', {})))"
        )
        result = subprocess.run([sys.executable, "-c", script, str(config_path), str(ROOT)],
                                cwd=MCP, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["data"]["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
