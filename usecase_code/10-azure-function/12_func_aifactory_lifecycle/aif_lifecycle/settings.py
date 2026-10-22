"""App settings (environment variables), validated once.

Secrets are read from Key Vault by name with the Function's managed identity (AIF_KEY_VAULT_NAME plus
AIF_*_SECRET_NAME), over the VNet like any private endpoint. App Service Key Vault *references* are not used: on Linux
plans other than Flex they need route-all, which would cut the app's GitHub egress. A value that still looks like an
unresolved reference is refused (fail closed) instead of being used as a secret.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .domain.errors import ValidationFailed
from .domain.ids import parse_any

BACKENDS = ("mock", "rest", "sdk")
EXECUTORS = ("inprocess", "github-dummy", "github-runner")
STORES = ("memory", "file", "table")
EVENT_PROCESSING = ("inline", "queue")
DELETES = ("refuse", "simulate", "allow")
_REFERENCE = "@Microsoft.KeyVault("
# (plain value setting, Key Vault secret name setting)
_SECRETS = {"event": ("AIF_EVENT_SECRET", "AIF_EVENT_SECRET_NAME"),
            "github": ("AIF_GITHUB_TOKEN", "AIF_GITHUB_TOKEN_NAME"),
            "factory": ("AIF_FACTORY_API_KEY", "AIF_FACTORY_API_KEY_NAME")}


class SecretReader(Protocol):
    def get(self, name: str) -> str: ...


def secret_value(env: Mapping[str, str], kind: str, vault: SecretReader | None) -> str | None:
    value_name, secret_name = _SECRETS[kind]
    value = env.get(value_name) or (env.get("AIFACTORY_API_KEY") if kind == "factory" else None)
    if value and value.strip().startswith(_REFERENCE):
        raise ValidationFailed(f"{value_name} is an unresolved Key Vault reference. Use {secret_name} with "
                               "AIF_KEY_VAULT_NAME so the Function reads the secret itself.")
    name = env.get(secret_name)
    if not name:
        return value or None
    if vault is None:
        raise ValidationFailed(f"{secret_name} needs AIF_KEY_VAULT_NAME.")
    return vault.get(name)


def _choice(env: Mapping[str, str], name: str, choices: tuple[str, ...], default: str) -> str:
    value = (env.get(name) or default).strip().lower()
    if value not in choices:
        raise ValidationFailed(f"{name} must be one of {', '.join(choices)}.")
    return value


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name)
    try:
        value = int(raw) if raw not in (None, "") else default
    except ValueError:
        raise ValidationFailed(f"{name} must be a whole number.") from None
    if not low <= value <= high:
        raise ValidationFailed(f"{name} must be between {low} and {high}.")
    return value


def _list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    backend: str = "mock"
    executor: str = "inprocess"
    store: str = "memory"
    store_path: str = ".aif-lifecycle-state.json"
    table_account: str | None = None
    table_name: str = "aiflifecycle"
    factory_api_url: str = "http://127.0.0.1:8765"
    factory_api_key: str | None = field(default=None, repr=False)
    factory_folder: str | None = None
    github_repository: str | None = None
    github_token: str | None = field(default=None, repr=False)
    github_api_url: str = "https://api.github.com"
    github_ref: str = "main"
    dummy_workflow: str = "aif-dummy-step.yml"
    dummy_duration_seconds: int = 75
    ops_workflow: str = "aif-ops.yml"
    runner_timeout_seconds: int = 900
    event_secrets: list[bytes] = field(default_factory=list, repr=False)
    event_processing: str = "inline"
    event_queue: str = "aif-github-events"
    queue_account: str | None = None
    protected_ids: list[str] = field(default_factory=list)
    review_ttl_seconds: int = 600
    poll_after_seconds: int = 120
    key_vault_name: str | None = None
    required_role: str | None = None
    deletes: str = "refuse"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, vault: SecretReader | None = None) -> "Settings":
        env = os.environ if env is None else env
        protected = _list(env.get("AIF_SELF_PROJECT_ID")) + _list(env.get("AIF_PROTECTED_IDS"))
        for item in protected:
            parse_any(item)
        event_secret = secret_value(env, "event", vault)
        github_token = secret_value(env, "github", vault)
        factory_key = secret_value(env, "factory", vault)
        settings = cls(
            backend=_choice(env, "AIF_BACKEND", BACKENDS, "mock"),
            executor=_choice(env, "AIF_EXECUTOR", EXECUTORS, "inprocess"),
            store=_choice(env, "AIF_STORE", STORES, "memory"),
            store_path=env.get("AIF_STORE_PATH") or cls.store_path,
            table_account=env.get("AIF_TABLE_ACCOUNT") or None,
            table_name=env.get("AIF_TABLE_NAME") or cls.table_name,
            factory_api_url=env.get("AIF_FACTORY_API_URL") or cls.factory_api_url,
            factory_api_key=factory_key,
            factory_folder=env.get("AIF_FACTORY_FOLDER") or None,
            github_repository=env.get("AIF_GITHUB_REPOSITORY") or None,
            github_token=github_token,
            github_api_url=env.get("AIF_GITHUB_API_URL") or cls.github_api_url,
            github_ref=env.get("AIF_GITHUB_REF") or cls.github_ref,
            dummy_workflow=env.get("AIF_DUMMY_WORKFLOW") or cls.dummy_workflow,
            dummy_duration_seconds=_int(env, "AIF_DUMMY_DURATION_SECONDS", 75, 5, 600),
            ops_workflow=env.get("AIF_OPS_WORKFLOW") or cls.ops_workflow,
            runner_timeout_seconds=_int(env, "AIF_RUNNER_TIMEOUT_SECONDS", 900, 120, 7200),
            event_secrets=[item.encode("utf-8") for item in _list(event_secret)],
            event_processing=_choice(env, "AIF_EVENT_PROCESSING", EVENT_PROCESSING, "inline"),
            event_queue=env.get("AIF_EVENT_QUEUE") or cls.event_queue,
            queue_account=env.get("AIF_EVENT_QUEUE_ACCOUNT") or env.get("AzureWebJobsStorage__accountName") or None,
            protected_ids=protected,
            review_ttl_seconds=_int(env, "AIF_REVIEW_TTL_SECONDS", 600, 30, 3600),
            poll_after_seconds=_int(env, "AIF_POLL_AFTER_SECONDS", 120, 15, 3600),
            key_vault_name=env.get("AIF_KEY_VAULT_NAME") or None,
            required_role=(env.get("AIF_REQUIRED_ROLE") or "").strip() or None,
            deletes=_choice(env, "AIF_DELETES", DELETES, "refuse"),
        )
        settings._check()
        if settings.required_role and (env.get("WEBSITE_AUTH_ENABLED") or "").strip().lower() != "true":
            # Only App Service authentication sets X-MS-CLIENT-PRINCIPAL; without it a caller could forge the header.
            raise ValidationFailed("AIF_REQUIRED_ROLE needs App Service authentication (Microsoft Entra ID) on the app.")
        return settings

    def _check(self) -> None:
        if self.store == "table" and not self.table_account:
            raise ValidationFailed("AIF_STORE=table needs AIF_TABLE_ACCOUNT (the storage account name).")
        if self.backend in ("rest", "sdk") and self.executor != "github-runner" and not self.factory_folder:
            raise ValidationFailed("AIF_BACKEND=rest|sdk needs AIF_FACTORY_FOLDER (the azurefactory folder on the API host).")
        if self.executor in ("github-dummy", "github-runner") and not (self.github_repository and self.github_token):
            raise ValidationFailed(f"AIF_EXECUTOR={self.executor} needs AIF_GITHUB_REPOSITORY and AIF_GITHUB_TOKEN.")
        if self.executor == "github-dummy" and self.backend != "mock":
            raise ValidationFailed("AIF_EXECUTOR=github-dummy runs dummy workflows and only pairs with AIF_BACKEND=mock.")
        if self.executor == "github-runner" and self.backend == "mock":
            raise ValidationFailed("AIF_EXECUTOR=github-runner calls the real Factory API; use AIF_BACKEND=rest or sdk.")
        if self.executor == "github-runner" and not self.event_secrets:
            raise ValidationFailed("AIF_EXECUTOR=github-runner signs runner requests and checks results with the event "
                                   "secret; set AIF_EVENT_SECRET_NAME.")
        if self.event_processing == "queue" and not self.queue_account:
            raise ValidationFailed("AIF_EVENT_PROCESSING=queue needs AzureWebJobsStorage__accountName or AIF_EVENT_QUEUE_ACCOUNT.")
