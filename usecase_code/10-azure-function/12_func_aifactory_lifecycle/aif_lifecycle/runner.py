"""Runner entry point: aif-ops.yml runs `python -m aif_lifecycle.runner` on the management runner, next to the API.

It makes the one Factory API call in AIF_RUNNER_REQUEST through the REST or SDK adapter on loopback and POSTs one
signed result to the Function (AIF_RESULTS_URL). Before calling, it checks that the Function signed the request, that
it has not expired and that the workflow inputs (the run name) describe it. A confirm is submitted exactly once: a
re-run of its job does nothing. Only the result post is retried, because the Function ignores a result it has
already applied.

Settings come from the environment, over `runner.json` in AIF_LIFECYCLE_HOME (same names). Secrets are read from Key
Vault by name with the VM's managed identity (AIF_KEY_VAULT_NAME plus AIF_FACTORY_API_KEY_NAME / AIF_EVENT_SECRET_NAME)
or taken from the environment (the workflow passes the event secret from a repository secret).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .adapters.rest_backend import is_loopback
from .application.runner_protocol import RunnerRequest, classify_confirm_failure, decode_request, result_body
from .composition import factory_api_backend
from .domain.errors import LifecycleError, ValidationFailed
from .settings import secret_value
from .signatures import sign

ATTEMPTS = 3
RERUN_REFUSED = 3
_INPUTS = (("AIF_OPERATION_ID", "operation_id"), ("AIF_STEP", "step"), ("AIF_ACTION", "action"), ("AIF_NONCE", "nonce"))
_pause = time.sleep


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main(env: Mapping[str, str] | None = None, *, vault=None, out=None) -> int:
    env = _environment(os.environ if env is None else env)
    out = out or sys.stdout
    results_url = _results_url(env.get("AIF_RESULTS_URL"))
    if vault is None and env.get("AIF_KEY_VAULT_NAME"):
        from .adapters.keyvault import KeyVaultSecrets
        vault = KeyVaultSecrets(env["AIF_KEY_VAULT_NAME"])
    secrets = [item.strip().encode("utf-8") for item in (secret_value(env, "event", vault) or "").split(",")
               if item.strip()]
    if not secrets:
        raise ValidationFailed("AIF_EVENT_SECRET or AIF_EVENT_SECRET_NAME is required to check requests and sign results.")
    request = decode_request(env.get("AIF_RUNNER_REQUEST") or "", secrets, now=time.time())
    _check_inputs(request, env)
    if request.action == "confirm" and int(env.get("GITHUB_RUN_ATTEMPT") or "1") > 1:
        print("aif-ops: a confirmation is submitted once, so this re-run does nothing; the Function treats the call "
              "as uncertain until the Factory API's jobs are checked.", file=out)
        return RERUN_REFUSED
    body = execute(request, env, vault, run_id=env.get("GITHUB_RUN_ID"))
    posted = post_result(results_url, secrets[0], body)
    print(f"aif-ops {request.action} for {request.operation_id}/{request.step}: {body['outcome']}; "
          f"result {'posted' if posted else 'NOT posted'}", file=out)
    return 0 if posted else 1


def execute(request: RunnerRequest, env: Mapping[str, str], vault, *, run_id: str | None = None) -> dict[str, Any]:
    """Make the call and describe what happened; every failure becomes a result, none is swallowed."""
    parts: dict[str, Any] = {}
    catalog = None
    backend = None
    try:
        # A signed request is not enough for a delete: the runner's own settings must allow real deletes as well.
        backend = factory_api_backend(request.backend, env.get("AIF_FACTORY_API_URL") or "http://127.0.0.1:8765",
                                      secret_value(env, "factory", vault), env.get("AIF_FACTORY_FOLDER"),
                                      allow_deletes=(env.get("AIF_ALLOW_REAL_DELETES") or "").strip().lower() == "true")
        if request.action == "catalog":
            catalog = backend.catalog_payload()
        elif request.action == "prepare":
            parts["preview"] = backend.prepare(request.request)
        elif request.action == "confirm":
            parts["confirm"] = backend.confirm(request.request, request.preview, request.phrase)
        else:
            parts["status"] = backend.job_status(request.job or {})
        outcome = "ok"
    except Exception as error:  # noqa: BLE001 - reported to the Function, which decides what it means
        outcome = classify_confirm_failure(error) if request.action == "confirm" else "error"
        parts = {"error": _error(error)}
    if catalog is None and backend is not None:
        catalog = _catalog(backend)
    return result_body(request, outcome=outcome, run_id=run_id, catalog=catalog, **parts)


def post_result(url: str, secret: bytes, body: dict[str, Any], *, timeout: float = 30.0) -> bool:
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": sign(secret, data),
               "X-AIF-Result-Id": str(body["resultId"]), "User-Agent": "aif-lifecycle-runner"}
    opener = build_opener(ProxyHandler({}), _NoRedirect)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with opener.open(Request(url, data=data, method="POST", headers=headers), timeout=timeout):
                return True
        except HTTPError as error:
            if error.code < 500 and error.code not in (408, 429):
                return False  # the Function refused the result (signature, shape): sending it again will not help
        except (URLError, TimeoutError, socket.timeout):
            pass
        if attempt < ATTEMPTS:
            _pause(min(2 ** attempt, 10))
    return False


def _check_inputs(request: RunnerRequest, env: Mapping[str, str]) -> None:
    """The workflow inputs, and so the run name the Function correlates, must describe the signed request."""
    for name, field in _INPUTS:
        if env.get(name) != str(getattr(request, field)):
            raise ValidationFailed(f"{name} does not match the signed request.", code="invalid-runner-request")


def _catalog(backend) -> dict[str, Any] | None:
    try:
        return backend.catalog_payload()
    except Exception:  # noqa: BLE001 - the snapshot is a bonus; the call's own outcome is what matters
        return None


def _error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, LifecycleError):
        return {"code": error.code, "detail": error.detail}
    return {"code": "runner-error", "detail": f"The runner failed with {type(error).__name__}."}


def _results_url(url: str | None) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.query:
        raise ValidationFailed("AIF_RESULTS_URL must be the Function's https URL of /api/v1/runner/results.")
    if parsed.scheme == "http" and not is_loopback(parsed.hostname):
        raise ValidationFailed("AIF_RESULTS_URL must use https; plain http is allowed only to loopback.")
    return str(url)


def _environment(env: Mapping[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    home = env.get("AIF_LIFECYCLE_HOME")
    if home and (Path(home) / "runner.json").is_file():
        settings = json.loads((Path(home) / "runner.json").read_text(encoding="utf-8"))
        merged.update({str(key): str(value) for key, value in settings.items()})
    merged.update({key: value for key, value in env.items() if value not in (None, "")})
    return merged


if __name__ == "__main__":
    sys.exit(main())
