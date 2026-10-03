"""Azure access for the health model tooling.

Only the operations this tool needs are built here; callers cannot pass
arbitrary ``az`` commands. On Windows the Azure CLI is invoked through its
bundled Python (never through ``az.cmd``) so URLs with ``&`` are not
interpreted by a batch shell. Raw CLI output is never re-raised: errors carry
the ARM error code and message only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .client import ARM, HealthModelError

ARG_URL = f"{ARM}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
PROVIDER_API = "2021-04-01"
NAMESPACE = "Microsoft.CloudHealth"
ARM_ERROR = re.compile(r"\{.*\}", re.S)


def az_command() -> list[str]:
    launcher = shutil.which("az.cmd") or shutil.which("az")
    if not launcher:
        raise RuntimeError("Azure CLI is required; 'az' was not found on PATH.")
    path = Path(launcher)
    if path.suffix.lower() in (".cmd", ".bat"):
        python = path.parent.parent / "python.exe"
        if not python.is_file():
            raise RuntimeError("Azure CLI bundled Python is unavailable; refusing a batch-shell fallback.")
        return [str(python), "-IBm", "azure.cli"]
    return [str(path)]


def default_runner(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*az_command(), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", input=input_text, shell=False, timeout=3600)


def arm_error(result: subprocess.CompletedProcess, purpose: str) -> HealthModelError:
    """Build an error from the ARM error document only; never echo raw CLI output."""
    code, message = "AzureCommandFailed", ""
    for candidate in ARM_ERROR.findall(result.stderr or ""):
        try:
            document = json.loads(candidate)
        except ValueError:
            continue
        error = document.get("error", document) if isinstance(document, dict) else {}
        if isinstance(error, dict) and error.get("code"):
            code = re.sub(r"[^A-Za-z0-9.]", "", str(error["code"]))[:80] or code
            message = str(error.get("message", ""))[:600]
            break
    text = f"{purpose} failed ({code})" + (f": {message}" if message else ".")
    return HealthModelError(text, code)


class AzCliTransport:
    """ARM transport through ``az rest`` using the signed-in Azure CLI identity."""

    def __init__(self, runner=None):
        self.runner = runner or default_runner

    def request(self, method: str, url: str, body: dict | None = None):
        if not url.startswith(f"{ARM}/"):
            raise ValueError("Only Azure Resource Manager URLs are allowed.")
        args = ["rest", "--method", method.lower(), "--url", url, "--output", "json", "--only-show-errors"]
        path = None
        try:
            if body is not None:
                handle, path = tempfile.mkstemp(prefix="hm-body-", suffix=".json")
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(body, stream)
                args += ["--body", f"@{path}", "--headers", "Content-Type=application/json"]
            result = self.runner(args)
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
        if result.returncode:
            raise arm_error(result, f"{method.upper()} {urlsplit(url).path}")
        text = (result.stdout or "").strip()
        return json.loads(text) if text else None


class TokenTransport:
    """ARM transport with an azure-identity style credential (``get_token(scope)``)."""

    def __init__(self, credential, timeout: int = 60):
        self.credential = credential
        self.timeout = timeout

    def request(self, method: str, url: str, body: dict | None = None):
        if not url.startswith(f"{ARM}/"):
            raise ValueError("Only Azure Resource Manager URLs are allowed.")
        token = self.credential.get_token(f"{ARM}/.default").token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method.upper(), headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            raise arm_error(subprocess.CompletedProcess([], 1, "", raw), f"{method.upper()} {urlsplit(url).path}") from None
        return json.loads(payload) if payload else None


class AzureBoundary:
    """The exact Azure operations used by plan/deploy, scoped to one subscription."""

    def __init__(self, subscription_id: str, runner=None, sleep=time.sleep):
        self.subscription_id = subscription_id
        self.runner = runner or default_runner
        self.transport = AzCliTransport(self.runner)
        self.sleep = sleep

    def _json(self, args: list[str], purpose: str):
        result = self.runner(args)
        if result.returncode:
            raise arm_error(result, purpose)
        text = (result.stdout or "").strip()
        return json.loads(text) if text else {}

    def verify_account(self, tenant_id: str) -> dict:
        try:
            account = self._json(["account", "show", "--subscription", self.subscription_id, "--output", "json",
                                  "--only-show-errors"], "Reading the signed-in Azure account")
        except HealthModelError as error:
            raise RuntimeError(f"{error} Sign in with 'az login' and select the configured subscription.") from None
        if (str(account.get("id", "")).lower() != self.subscription_id.lower()
                or str(account.get("tenantId", "")).lower() != tenant_id.lower()):
            raise RuntimeError("The signed-in Azure account does not match the configured tenant/subscription. "
                               "No Azure reads or writes were performed beyond the account check.")
        return account

    def provider(self) -> dict:
        url = f"{ARM}/subscriptions/{self.subscription_id}/providers/{NAMESPACE}?api-version={PROVIDER_API}"
        document = self.transport.request("GET", url) or {}
        regions = set()
        for item in document.get("resourceTypes", []):
            if item.get("resourceType", "").lower() == "healthmodels":
                regions = {r.lower().replace(" ", "") for r in item.get("locations", [])}
        return {"registrationState": document.get("registrationState", "Unknown"), "regions": regions}

    def register_provider(self, timeout: int = 600) -> None:
        self._json(["provider", "register", "--namespace", NAMESPACE, "--subscription", self.subscription_id,
                    "--only-show-errors"], f"Registering {NAMESPACE}")
        deadline = time.monotonic() + timeout
        while self.provider()["registrationState"] != "Registered":
            if time.monotonic() > deadline:
                raise RuntimeError(f"{NAMESPACE} registration did not complete in time; rerun later.")
            self.sleep(10)

    def discover(self, resource_groups: list[str], include_health_models: bool = False) -> list[dict]:
        groups = ", ".join(f"'{g}'" for g in resource_groups if g)
        where = f"resourceGroup in~ ({groups})"
        if include_health_models:
            where = f"({where}) or type =~ 'microsoft.cloudhealth/healthmodels'"
        query = (f"resources | where subscriptionId =~ '{self.subscription_id}' | where {where} "
                 "| project id, name, type, kind, location, resourceGroup, tags, hns = tobool(properties.isHnsEnabled)")
        rows, skip = [], None
        while True:
            options = {"resultFormat": "objectArray", "$top": 1000}
            if skip:
                options["$skipToken"] = skip
            page = self.transport.request("POST", ARG_URL, {"subscriptions": [self.subscription_id],
                                                             "query": query, "options": options}) or {}
            rows.extend(page.get("data", []))
            skip = page.get("$skipToken")
            if not skip:
                return rows

    def _deployment_args(self, verb: str, resource_group: str, template: Path, parameters: Path) -> list[str]:
        return ["deployment", "group", verb, "--subscription", self.subscription_id, "--resource-group",
                resource_group, "--template-file", str(template), "--parameters", f"@{parameters}"]

    def what_if(self, resource_group: str, template: Path, parameters: Path) -> dict:
        result = self._json([*self._deployment_args("what-if", resource_group, template, parameters),
                             "--no-pretty-print", "--output", "json", "--only-show-errors"], "What-if")
        counts: dict[str, int] = {}
        for change in result.get("changes", []):
            counts[change.get("changeType", "Unknown")] = counts.get(change.get("changeType", "Unknown"), 0) + 1
        return counts

    def deploy(self, name: str, resource_group: str, template: Path, parameters: Path) -> dict:
        args = self._deployment_args("create", resource_group, template, parameters)
        args[3:3] = ["--name", name]
        return self._json([*args, "--mode", "Incremental", "--output", "json", "--only-show-errors"],
                          f"Deploying health model {name}")
