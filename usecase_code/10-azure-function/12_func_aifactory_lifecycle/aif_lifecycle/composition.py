"""Composition root: the only place that chooses adapters (AIF_BACKEND, AIF_EXECUTOR, AIF_STORE, ...)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from .application.guard import SelfProtection
from .application.service import LifecycleService
from .domain.errors import ValidationFailed
from .http_api import LifecycleHttpApi
from .settings import Settings


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class Runtime:
    settings: Settings
    service: LifecycleService
    api: LifecycleHttpApi


def _store(settings: Settings):
    from .adapters import stores

    if settings.store == "table":
        return stores.TableStore(settings.table_account, settings.table_name)
    if settings.store == "file":
        return stores.FileStore(settings.store_path)
    return stores.MemoryStore()


def _backend(settings: Settings, store, clock):
    if settings.backend == "mock":
        from .adapters.mock_backend import MockFactoryBackend
        return MockFactoryBackend(store, clock=clock, review_ttl_seconds=settings.review_ttl_seconds)
    if settings.backend == "rest":
        from .adapters.rest_backend import RestFactoryBackend, RestTransport
        return RestFactoryBackend(RestTransport(settings.factory_api_url, settings.factory_api_key), settings.factory_folder)
    from .adapters.sdk_backend import SdkFactoryBackend
    return SdkFactoryBackend(settings.factory_api_url, settings.factory_api_key, settings.factory_folder)


def _tracker(settings: Settings, backend):
    from .adapters import trackers

    if settings.executor == "inprocess":
        return trackers.InstantTracker() if settings.backend == "mock" else trackers.ApiJobTracker(backend)
    if settings.executor == "github-dummy":
        from .adapters.github import GitHubClient
        github = GitHubClient(settings.github_repository, settings.github_token, api_url=settings.github_api_url)
        return trackers.DummyWorkflowTracker(github, workflow=settings.dummy_workflow, ref=settings.github_ref,
                                             duration_seconds=settings.dummy_duration_seconds)
    raise ValidationFailed("AIF_EXECUTOR=github-runner arrives with the real-API pass.")


def build_runtime(env: Mapping[str, str] | None = None, *, vault=None) -> Runtime:
    env = os.environ if env is None else env
    if vault is None and env.get("AIF_KEY_VAULT_NAME"):
        from .adapters.keyvault import KeyVaultSecrets
        vault = KeyVaultSecrets(env["AIF_KEY_VAULT_NAME"])
    settings = Settings.from_env(env, vault=vault)
    clock = SystemClock()
    store = _store(settings)
    backend = _backend(settings, store, clock)
    service = LifecycleService(backend=backend, tracker=_tracker(settings, backend), store=store,
                               guard=SelfProtection(settings.protected_ids), clock=clock,
                               poll_after_seconds=settings.poll_after_seconds)
    enqueue = None
    if settings.event_processing == "queue":
        from .adapters.queue import EventQueue
        enqueue = EventQueue(settings.queue_account, settings.event_queue).send
    return Runtime(settings=settings, service=service, api=LifecycleHttpApi(service, event_secrets=settings.event_secrets,
                                                                             enqueue=enqueue))
