"""Prepared private VM adapter for the synchronous Agent Chat portal Run Command.

The operator must install Bicep on PATH. Azure CLI uses that prepared binary, never an automatic compiler download
into the isolated AZURE_CONFIG_DIR.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import agent_chat_entry as entry

UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
FQDN = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.azurecontainerapps\.io")
STAGES = ("46-factory-chat-agent", "47-aifactory-agent-live-voice")
TARGET_FIELDS = (
    "dev_test_prod_sub_id", "tenantId", "project_number_000", "dev_test_prod", "projectResourceGroup",
    "admin_aifactoryPrefixRG", "projectPrefix", "admin_locationSuffix", "admin_aifactorySuffixRG", "projectSuffix",
    "admin_location", "aifactoryAgentContainerAppsEnvironment",
)


def inputs(environ):
    if sys.version_info < (3, 12):
        raise ValueError("AIF_PYTHON must be a prepared Python 3.12+ executable.")
    required = ("AIF_CONSUMER_ROOT", "AIF_PROJECT_NUMBER", "AIF_PYTHON", "AIF_IDENTITY_CLIENT_ID",
                "AIF_SUBSCRIPTION_ID", "AIF_TENANT_ID", "AIF_RUN_ID")
    for name in required:
        if not environ.get(name, "").strip():
            raise ValueError(f"{name} is required.")
    project = environ["AIF_PROJECT_NUMBER"]
    if not re.fullmatch(r"[0-9]{3}", project) or project == "000":
        raise ValueError("AIF_PROJECT_NUMBER must be 001-999 (Dev only).")
    for name in ("AIF_IDENTITY_CLIENT_ID", "AIF_SUBSCRIPTION_ID", "AIF_TENANT_ID"):
        if not UUID.fullmatch(environ[name]) or not int(environ[name].replace("-", ""), 16):
            raise ValueError(f"{name} must be a nonzero UUID.")
    root = Path(environ["AIF_CONSUMER_ROOT"])
    python = Path(environ["AIF_PYTHON"])
    if not root.is_absolute() or not root.is_dir() or not (root / ".git").exists():
        raise ValueError("AIF_CONSUMER_ROOT must be an existing absolute consumer checkout.")
    root = root.resolve()
    if any(part.lower() in {"_work", "_temp"} for part in root.parts):
        raise ValueError("AIF_CONSUMER_ROOT must be durable, not an ephemeral pipeline _work or _temp checkout.")
    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("AIF_PYTHON must be an existing absolute executable.")
    if not shutil.which("bicep", path=environ.get("PATH", "")):
        raise ValueError("A prepared bicep executable must be installed on PATH; the portal does not install a compiler.")
    accelerator = root / entry.SUBMODULE
    paths = [accelerator / "bootstrap/lib/agent_chat_entry.py",
             accelerator / "bootstrap/lib/agent_chat_portal.py"]
    paths.extend(accelerator / entry.AGENT_FACTORY / folder / "deploy.py" for folder in STAGES)
    if any(not path.is_file() for path in paths):
        raise ValueError("Update the prepared accelerator submodule; the portal adapter and both deployers are required.")
    args = ["--consumer-root", str(root), "--to-project", project, "--environment", "dev", "--apply"]
    explicit = environ.get("AIF_CONFIGURATION_PATH", "")
    if explicit:
        path = Path(explicit)
        args.extend(["--config", str(path if path.is_absolute() else root / path)])
    options = entry.parse(args)
    path = entry.resolve_configuration(root, project, options["config"])
    values = entry.pipeline_values(path, root, options)
    for config_key, parameter in (("dev_sub_id", "AIF_SUBSCRIPTION_ID"), ("tenantId", "AIF_TENANT_ID")):
        if values.get(config_key, "").lower() != environ[parameter].lower():
            raise ValueError(f"Selected project {config_key} does not match {parameter}.")
    return root, args, values


@contextmanager
def isolated_runtime(environ):
    # Keep both CLI credentials and stage 47's generated configuration/venv/cache outside the consumer checkout.
    base = Path(environ.get("HOME") or Path.home()) / ".cache/esaf-agent-chat"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=base) as directory:
        work = Path(directory)
        runtime = {**environ, "AZURE_CONFIG_DIR": str(work / "azure"),
                   "AZURE_BICEP_USE_BINARY_FROM_PATH": "true",
                   "RUNNER_TEMP": str(work), "AGENT_TEMPDIRECTORY": str(work),
                   "AGENT_TOOLSDIRECTORY": str(work / "tools"), "RUNNER_TOOL_CACHE": str(work / "tools"),
                   "PYTHONDONTWRITEBYTECODE": "1"}
        original = dict(os.environ)
        os.environ.clear()
        os.environ.update(runtime)
        try:
            yield runtime
        finally:
            os.environ.clear()
            os.environ.update(original)


def az(arguments, run):
    try:
        result = run(["az", *arguments, "--only-show-errors", "--output", "json"],
                     check=False, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Azure CLI {arguments[0]} timed out.") from error
    if result.returncode:
        raise RuntimeError(f"Azure CLI {arguments[0]} failed (exit {result.returncode}).")
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError as error:
        raise RuntimeError(f"Azure CLI {arguments[0]} did not return JSON.") from error


def verified_fqdn(result, values, run):
    from agent_factory.agent_live_voice import APPS_API, LiveVoiceRequest, app_name, scope_key

    request = LiveVoiceRequest.from_values(values)
    outputs = result.get("outputs")
    app = outputs.get("app") if isinstance(outputs, dict) else None
    if (not isinstance(app, dict) or app.get("deployment_state") != "Succeeded"
            or outputs.get("scope") != scope_key(request) or outputs.get("voice") is not True):
        raise RuntimeError("Agent chat application did not return successful deployment outputs.")
    fqdn = app.get("fqdn")
    if (not isinstance(fqdn, str) or len(fqdn) > 253 or not FQDN.fullmatch(fqdn)
            or ".." in fqdn or not fqdn.startswith(app_name(request) + ".")):
        raise RuntimeError("Agent chat application returned an invalid Container Apps fqdn.")
    resource = (f"/subscriptions/{request.subscription_id}/resourceGroups/{request.resource_group}"
                f"/providers/Microsoft.App/containerApps/{app_name(request)}")
    deployed = az(["rest", "--method", "get", "--url",
                   f"https://management.azure.com{resource}?api-version={APPS_API}"], run)
    properties = deployed.get("properties", {})
    actual = properties.get("configuration", {}).get("ingress", {}).get("fqdn")
    if (deployed.get("id", "").lower() != resource.lower()
            or properties.get("provisioningState") != "Succeeded" or actual != fqdn):
        raise RuntimeError("Application fqdn/state does not match the selected project's Azure resource.")
    return fqdn


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError("Application readiness redirected; refusing another destination.")


def wait_ready(fqdn, *, open_url=None, attempts=30, delay=10, sleep=time.sleep):
    if not isinstance(fqdn, str) or not FQDN.fullmatch(fqdn) or ".." in fqdn:
        raise RuntimeError("Invalid application readiness fqdn.")
    # No bearer token, cookies, proxy credentials or redirect to an arbitrary destination.
    open_url = open_url or build_opener(ProxyHandler({}), NoRedirects()).open
    url = f"https://{fqdn}/health/ready"
    for attempt in range(attempts):
        try:
            with open_url(Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError(f"Application readiness returned HTTP {response.status}.")
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise RuntimeError("Application readiness response is too large.")
                try:
                    body = json.loads(raw)
                except ValueError as error:
                    raise RuntimeError("Application readiness did not return JSON.") from error
                if not isinstance(body, dict):
                    raise RuntimeError("Application readiness did not return a JSON object.")
                if body.get("status") not in {"ready", "not_ready"}:
                    raise RuntimeError("Application readiness returned an unknown status.")
                checks = body.get("checks", {})
                if isinstance(checks, dict) and checks.get("authentication") == "unconfigured":
                    raise RuntimeError("Application readiness reports unconfigured authentication.")
                if (body.get("status") == "ready" and isinstance(checks, dict)
                        and checks.get("authentication") == "configured"
                        and checks.get("knowledge") in {"ready", "last_successful"}):
                    return body
        except HTTPError as error:
            error.close()
            if error.code not in {404, 408, 429, 502, 503, 504}:
                raise RuntimeError(f"Application readiness returned HTTP {error.code}.") from error
        except URLError as error:
            reason = error.reason
            transient = isinstance(reason, (TimeoutError, ConnectionRefusedError, ConnectionResetError))
            transient |= isinstance(reason, socket.gaierror) and reason.errno in {socket.EAI_AGAIN, socket.EAI_NONAME}
            if isinstance(reason, ssl.SSLError) or not transient:
                raise RuntimeError("Application readiness connection failed.") from error
        except (TimeoutError, ConnectionRefusedError, ConnectionResetError):
            pass
        if attempt + 1 < attempts:
            sleep(delay)
    raise RuntimeError(f"Application readiness was unavailable after {attempts} attempts: {url}")


def main(environ=None, *, chat_runner=None, voice_runner=None, run=subprocess.run, readiness=None):
    environ = dict(os.environ if environ is None else environ)
    supplied_chat, supplied_voice = chat_runner, voice_runner
    try:
        root, args, values = inputs(environ)
        chat_runner = chat_runner or entry.launcher(root, STAGES[0])
        voice_runner = voice_runner or entry.launcher(root, STAGES[1])
        # The selected variables file, never stale pipeline environment values, owns deployment inputs.
        request_fields = set(TARGET_FIELDS)
        for runner in (chat_runner, voice_runner):
            for name in getattr(runner, "__globals__", {}).get("INPUTS", ()):
                request_fields.add(name)
                environ.pop(name, None)
        validated_contract = {name: values.get(name, "") for name in request_fields}
        validation = SimpleNamespace(command="validate", apply=False, skip_knowledge=False)
        for name, runner in zip(STAGES, (chat_runner, voice_runner)):
            result = runner(validation, {**environ, **values})
            if not isinstance(result, dict) or result.get("mode") != "validated":
                raise ValueError(f"{name} did not validate; refusing a skipped stage.")
    except (ValueError, RuntimeError) as error:
        print(f"Agent chat portal configuration error: {error}", file=sys.stderr)
        return 2

    results = {}
    def required_stage(name, runner):
        def apply(command, stage_environ):
            # The shared entry re-reads configuration. Reject retargeting before either stage can mutate Azure.
            changed = sorted(field for field, expected in validated_contract.items()
                             if stage_environ.get(field, "") != expected)
            if changed:
                raise RuntimeError(f"{name} configuration changed after validation: {', '.join(changed)}.")
            result = runner(command, stage_environ)
            if not isinstance(result, dict) or result.get("mode") != "apply":
                raise RuntimeError(f"{name} was skipped or not applied.")
            if name == "chat" and result.get("status") not in {"created", "updated", "unchanged"}:
                raise RuntimeError("Chat Agent did not report a completed apply.")
            if name == "voice" and result.get("mutations") is not True:
                raise RuntimeError("Agent chat application was not applied.")
            results[name] = result
            return result
        return apply

    try:
        with isolated_runtime(environ) as runtime:
            if supplied_chat is None or supplied_voice is None:
                # Stage 47 builds .build/wheels and a deployment bundle inside its source tree. Copy local source,
                # not Git history or an installed environment, so those writes never touch the consumer checkout.
                staged = Path(runtime["RUNNER_TEMP"]) / "source"
                shutil.copytree(root / entry.SUBMODULE, staged / entry.SUBMODULE,
                                ignore=shutil.ignore_patterns(".git", ".claude", ".scout", ".venv", "venv", "__pycache__",
                                                             ".build", "node_modules", ".pytest_cache"))
                chat_runner = supplied_chat or entry.launcher(staged, STAGES[0])
                voice_runner = supplied_voice or entry.launcher(staged, STAGES[1])
            az(["login", "--identity", "--client-id", environ["AIF_IDENTITY_CLIENT_ID"]], run)
            az(["account", "set", "--subscription", environ["AIF_SUBSCRIPTION_ID"]], run)
            account = az(["account", "show"], run)
            if (account.get("id", "").lower() != environ["AIF_SUBSCRIPTION_ID"].lower()
                    or account.get("tenantId", "").lower() != environ["AIF_TENANT_ID"].lower()):
                raise RuntimeError("Managed identity account does not match the selected subscription and tenant.")
            code = entry.main(args, chat_runner=required_stage("chat", chat_runner),
                              voice_runner=required_stage("voice", voice_runner))
            if code:
                return code
            fqdn = verified_fqdn(results["voice"], values, run)
            (readiness or wait_ready)(fqdn)
            print(json.dumps({"status": "ready", "url": f"https://{fqdn}", "run_id": environ["AIF_RUN_ID"],
                              "coverage": "Authentication configuration and knowledge; not end-to-end Foundry execution."}))
    except (ValueError, RuntimeError) as error:
        print(f"Agent chat portal failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
