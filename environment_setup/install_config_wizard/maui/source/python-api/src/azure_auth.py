"""Azure CLI authentication shared by the HTTP API and desktop applications."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import UUID, uuid4

from src import operations
from src.factory_scope import current_factory_scope


AuthState = Literal[
    "signed_in", "login_required", "signed_out", "signing_in", "signing_out",
    "unavailable", "error",
]
LOGIN_REQUIRED = "Azure sign-in expired or is required; choose Login to Azure."
SHARED_CACHE = "Uses the current OS user's shared Azure CLI sign-in, including other tooling."
CLI_UNAVAILABLE = "Azure CLI is not installed or cannot run. Install or repair Azure CLI and check the API process PATH."
_LOG = logging.getLogger(__name__)
_ACCOUNT_QUERY = "[].{id:id,tenantId:tenantId,isDefault:isDefault,accountName:user.name}"
_TOKEN_QUERY = "{expiresOn:expiresOn,tenant:tenant}"


@dataclass
class AzureAuthTenant:
    tenant_id: str
    needs_login: bool
    account_name: str = ""
    message: str = ""


@dataclass
class AzureAuthStatus:
    state: AuthState
    is_logged_in: bool = False
    account_name: str = ""
    tenant_id: str = ""
    message: str = ""
    tenants: list[AzureAuthTenant] = field(default_factory=list)
    operation_id: str | None = None


class AuthRequestError(ValueError):
    """Safe validation message that may be returned to an API client."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class _CliUnavailable(Exception):
    pass


class _CliError(Exception):
    pass


class _LoginRequired(Exception):
    pass


@dataclass(frozen=True)
class _Context:
    folder: str = ""
    tenant_ids: tuple[str, ...] = ()
    subscription_ids: tuple[str, ...] = ()


@dataclass
class _Job:
    context: _Context
    kind: str
    tenant_id: str | None
    status: AzureAuthStatus


def _guid(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value.strip()
    ):
        return ""
    return str(UUID(value.strip()))


def _account_name(value: Any) -> str:
    # The CLI user name is an email or service-principal ID, never raw CLI text.
    if not isinstance(value, str) or len(value) > 254:
        return ""
    if _guid(value) or re.fullmatch(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value):
        return value
    return ""


def _configured_guid(value: Any) -> str:
    if value is None or value == "" or (isinstance(value, str) and (
        not value.strip() or "<todo>" in value.casefold()
    )):
        return ""
    result = _guid(value)
    if not result:
        raise ValueError("Invalid configured tenant/subscription identifier")
    return result


def _context(folder: str | None) -> _Context:
    if folder is None:
        return _Context()
    try:
        if not isinstance(folder, str) or not folder.strip() or "\x00" in folder:
            raise ValueError
        path = Path(folder).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError
        path = path.resolve()
        scope = current_factory_scope(path)
        subscriptions = {_configured_guid(value) for value in scope["subscription_ids"]}
        tenants = {_configured_guid(value) for value in scope["tenant_ids"]}
        return _Context(
            os.path.normcase(str(path)), tuple(sorted(tenants - {""})),
            tuple(sorted(subscriptions - {""})),
        )
    except (OSError, ValueError):
        raise AuthRequestError(
            "AIFactory folder must be an existing absolute folder with readable, valid configuration."
        ) from None


class AzureAuthService:
    """Process-local jobs and a short, context-keyed metadata-only status cache."""

    CACHE_SECONDS = 20
    MAX_RECENT = 32

    def __init__(
        self, runner: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._runner = runner or subprocess.run
        self._clock = clock
        self._condition = threading.Condition()
        self._cache: OrderedDict[_Context, tuple[float, AzureAuthStatus]] = OrderedDict()
        self._checking: set[_Context] = set()
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._active: str | None = None
        self._generation = 0

    def _run(self, arguments: list[str], *, mutation: bool = False) -> Any:
        try:
            prefix = operations._azure_cli_command(operations.resolve_azure_cli())
        except (RuntimeError, OSError):
            raise _CliUnavailable from None
        env = os.environ.copy()
        env["AZURE_CORE_LOGIN_EXPERIENCE_V2"] = "off"
        env["AZURE_CORE_ENABLE_BROKER_ON_WINDOWS"] = "false"
        # Prevent a user's global debug/file logging settings from recording auth output.
        env["AZURE_CORE_LOG_LEVEL"] = "critical"
        env["AZURE_LOGGING_ENABLE_LOG_FILE"] = "false"
        try:
            result = self._runner(
                [*prefix, *arguments, "--only-show-errors"], shell=False,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=300 if mutation else 30,
                env=env,
            )
        except FileNotFoundError:
            raise _CliUnavailable from None
        except (OSError, subprocess.SubprocessError):
            raise _CliError from None
        if result.returncode:
            text = (result.stderr or "").casefold()
            if any(marker in text for marker in (
                "az login", "expired", "refresh token", "interaction_required",
                "interactionrequired", "aadsts500", "aadsts700", "not logged in",
                "no accounts", "please log in",
            )):
                raise _LoginRequired from None
            raise _CliError from None
        if mutation:
            return None
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError):
            raise _CliError from None

    def _accounts(self) -> list[dict[str, Any]]:
        raw = self._run(["account", "list", "--all", "--query", _ACCOUNT_QUERY, "--output", "json"])
        if not isinstance(raw, list):
            raise _CliError
        accounts = []
        for item in raw:
            if not isinstance(item, dict) or not _guid(item.get("tenantId")):
                raise _CliError
            accounts.append({
                "id": _guid(item.get("id")),
                "tenant_id": _guid(item["tenantId"]),
                "account_name": _account_name(item.get("accountName")),
                "is_default": item.get("isDefault") is True,
            })
        return accounts

    @staticmethod
    def _tenant_ids(context: _Context, accounts: list[dict[str, Any]]) -> list[str]:
        if context.tenant_ids:
            return list(context.tenant_ids)
        tenants = set(context.tenant_ids)
        tenants.update(
            account["tenant_id"] for account in accounts
            if account["id"] in context.subscription_ids
        )
        if not tenants and not context.subscription_ids:
            default = next((account for account in accounts if account["is_default"]), None)
            if default:
                tenants.add(default["tenant_id"])
        return sorted(tenants)

    def _token(self, tenant: str) -> None:
        metadata = self._run([
            "account", "get-access-token", "--tenant", tenant,
            "--resource", "https://management.azure.com/",
            "--query", _TOKEN_QUERY, "--output", "json",
        ])
        if not isinstance(metadata, dict):
            raise _CliError
        if _guid(metadata.get("tenant")) != tenant:
            raise _CliError
        expiry = metadata.get("expiresOn")
        if expiry is not None:
            try:
                timestamp = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).timestamp()
            except (ValueError, OverflowError, OSError):
                raise _CliError from None
            if timestamp <= time.time():
                raise _LoginRequired

    def _probe(self, context: _Context) -> AzureAuthStatus:
        try:
            accounts = self._accounts()
            tenant_ids = self._tenant_ids(context, accounts)
            conflicting = [
                account["id"] for account in accounts
                if account["id"] in context.subscription_ids and context.tenant_ids
                and account["tenant_id"] not in context.tenant_ids
            ]
            if conflicting:
                return AzureAuthStatus(
                    "error", message="Configured subscription tenant does not match Azure CLI account metadata: "
                    + ", ".join(conflicting)
                    + ". Check the active factory tenant/subscription configuration; no other tenant was queried.",
                )
            tenants = []
            errors = False
            for tenant in tenant_ids:
                name = next((
                    item["account_name"] for item in accounts if item["tenant_id"] == tenant
                ), "")
                try:
                    self._token(tenant)
                    result = AzureAuthTenant(tenant, False, name, "Azure CLI token is usable.")
                except _LoginRequired:
                    result = AzureAuthTenant(tenant, True, name, LOGIN_REQUIRED)
                except _CliError:
                    errors = True
                    result = AzureAuthTenant(
                        tenant, False, name,
                        "Could not verify Azure sign-in. Check connectivity and retry.",
                    )
                tenants.append(result)
            logged_in = bool(tenants) and not errors and all(not item.needs_login for item in tenants)
            state: AuthState = "signed_in" if logged_in else (
                "error" if errors else "login_required" if accounts else "signed_out"
            )
            message = (
                "Signed in to Azure CLI for all known required tenants. Resource access still depends on RBAC."
                if logged_in else "Could not verify Azure sign-in. Check connectivity and retry."
                if errors else LOGIN_REQUIRED
            )
            missing = set(context.subscription_ids) - {item["id"] for item in accounts}
            if missing:
                message += (
                    " Configured subscriptions missing from Azure CLI account metadata: "
                    + ", ".join(sorted(missing))
                    + ". Their tenant sign-in and resource access are unverified; this is not an RBAC test."
                )
            primary = next((
                item for item in tenants
                if any(a["is_default"] and a["tenant_id"] == item.tenant_id for a in accounts)
            ), tenants[0] if tenants else None)
            return AzureAuthStatus(
                state, logged_in, primary.account_name if primary else "",
                primary.tenant_id if primary else "", message + " " + SHARED_CACHE, tenants,
            )
        except _CliUnavailable:
            return AzureAuthStatus("unavailable", message=CLI_UNAVAILABLE)
        except (_CliError, _LoginRequired):
            return AzureAuthStatus("error", message="Could not read Azure CLI account metadata. Check Azure CLI and retry.")

    def _pending(self, context: _Context) -> AzureAuthStatus:
        job = self._jobs[self._active]
        if job.context == context:
            return copy.deepcopy(job.status)
        return AzureAuthStatus(
            job.status.state, message="Another Azure CLI authentication operation is in progress. " + SHARED_CACHE,
            operation_id=self._active,
        )

    def status(self, aifactory_folder: str | None = None) -> AzureAuthStatus:
        context = _context(aifactory_folder)
        with self._condition:
            while context in self._checking and not self._active:
                self._condition.wait()
            if self._active:
                return self._pending(context)
            cached = self._cache.get(context)
            if cached and self._clock() - cached[0] < self.CACHE_SECONDS:
                return copy.deepcopy(cached[1])
            generation = self._generation
            self._checking.add(context)
        try:
            result = self._probe(context)
            with self._condition:
                if self._active:
                    return self._pending(context)
                if generation == self._generation:
                    self._cache[context] = (self._clock(), copy.deepcopy(result))
                    self._cache.move_to_end(context)
                    while len(self._cache) > self.MAX_RECENT:
                        self._cache.popitem(last=False)
                    return result
        finally:
            with self._condition:
                self._checking.discard(context)
                self._condition.notify_all()
        # A concurrent auth mutation completed while this probe was running.
        return self.status(aifactory_folder)

    def login(self, aifactory_folder: str | None = None, tenant_id: str | None = None) -> AzureAuthStatus:
        if tenant_id is not None:
            tenant_id = _guid(tenant_id)
            if not tenant_id:
                raise AuthRequestError("tenant_id must be a tenant UUID.")
        return self._start("login", _context(aifactory_folder), tenant_id)

    def logout(self, aifactory_folder: str | None = None) -> AzureAuthStatus:
        return self._start("logout", _context(aifactory_folder), None)

    def operation(self, operation_id: str) -> AzureAuthStatus | None:
        with self._condition:
            job = self._jobs.get(operation_id)
            return copy.deepcopy(job.status) if job else None

    def _start(self, kind: str, context: _Context, tenant_id: str | None) -> AzureAuthStatus:
        with self._condition:
            if self._active:
                job = self._jobs[self._active]
                if (job.kind, job.context, job.tenant_id) == (kind, context, tenant_id):
                    return copy.deepcopy(job.status)
                raise AuthRequestError("An Azure authentication operation is already in progress.", 409)
            cached = self._cache.get(context)
            known = {item.tenant_id for item in cached[1].tenants} if cached else set(context.tenant_ids)
            # A worker revalidates against current CLI subscription metadata before login.
            if tenant_id and cached and known and tenant_id not in known:
                raise AuthRequestError("tenant_id does not belong to the selected factory/account context.")
            operation_id = str(uuid4())
            pending = AzureAuthStatus(
                "signing_in" if kind == "login" else "signing_out",
                message=(
                    "Azure browser sign-in is starting. Complete sign-in on the API host machine. "
                    if kind == "login" else "Signing out the OS user's shared Azure CLI account cache. "
                ) + SHARED_CACHE,
                tenants=copy.deepcopy(cached[1].tenants) if cached else [],
                operation_id=operation_id,
            )
            self._jobs[operation_id] = _Job(context, kind, tenant_id, pending)
            self._active = operation_id
            self._generation += 1
            self._cache.clear()
            while len(self._jobs) > self.MAX_RECENT:
                self._jobs.popitem(last=False)
            try:
                threading.Thread(
                    target=self._work, args=(operation_id,), daemon=True,
                    name="azure-cli-auth",
                ).start()
            except RuntimeError:
                self._active = None
                pending.state = "error"
                pending.message = "Could not start Azure authentication. Retry."
            self._condition.notify_all()
            return copy.deepcopy(pending)

    def _work(self, operation_id: str) -> None:
        job = self._jobs[operation_id]
        try:
            if job.kind == "login":
                before = self._probe(job.context)
                if before.state in ("unavailable", "error"):
                    result = before
                else:
                    known = {item.tenant_id for item in before.tenants}
                    if job.tenant_id and known and job.tenant_id not in known:
                        raise AuthRequestError("tenant_id does not belong to the selected factory/account context.")
                    failing = [item.tenant_id for item in before.tenants if item.needs_login]
                    if not job.tenant_id and len(failing) > 1:
                        raise AuthRequestError("Choose a tenant requiring sign-in, then choose Login to Azure.")
                    tenant = job.tenant_id or (failing[0] if failing else before.tenant_id)
                    arguments = ["login"]
                    if tenant:
                        arguments.extend(["--tenant", tenant])
                    self._run(
                        [*arguments, "--allow-no-subscriptions", "--output", "none"], mutation=True,
                    )
                    result = self._probe(job.context)
                    if result.state == "signed_out":
                        result = AzureAuthStatus("error", message="Azure sign-in did not establish a usable account. Retry Login to Azure.")
            else:
                before = self._accounts()
                self._run(["logout", "--output", "none"], mutation=True)
                after = self._accounts()
                if after:
                    raise _CliError
                for tenant in sorted(set(job.context.tenant_ids) | {a["tenant_id"] for a in before}):
                    try:
                        self._token(tenant)
                    except _LoginRequired:
                        continue
                    raise _CliError
                result = AzureAuthStatus(
                    "signed_out",
                    message="Signed out of the OS user's shared Azure CLI cache. Other Azure CLI tooling is also signed out.",
                    tenants=[AzureAuthTenant(tenant, True, message=LOGIN_REQUIRED) for tenant in job.context.tenant_ids],
                )
        except AuthRequestError as exc:
            result = AzureAuthStatus("error", message=str(exc))
        except _CliUnavailable:
            result = AzureAuthStatus("unavailable", message=CLI_UNAVAILABLE)
        except (_CliError, _LoginRequired):
            result = AzureAuthStatus(
                "error", message=(
                    "Azure sign-in was cancelled, timed out, or could not complete. Retry Login to Azure."
                    if job.kind == "login" else
                    "Azure CLI logout could not be verified. Check Azure CLI and retry; the shared cache may still be signed in."
                ),
            )
        except Exception as exc:
            # Never strand a job or log exception text/tracebacks containing CLI output.
            _LOG.error("Azure authentication worker failed (%s)", type(exc).__name__)
            result = AzureAuthStatus("error", message="Azure authentication could not complete. Retry or contact support.")
        with self._condition:
            job.status = replace(result, operation_id=operation_id)
            self._active = None
            self._generation += 1
            self._cache.clear()
            self._condition.notify_all()


azure_auth_service = AzureAuthService()
