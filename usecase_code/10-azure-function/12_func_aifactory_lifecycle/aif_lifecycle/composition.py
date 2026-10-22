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


def factory_api_backend(name: str, url: str, key: str | None, folder: str | None, *, allow_deletes: bool = False):
    """Option 1 (REST) or option 2 (SDK) against a Factory API on this host's loopback (the Function or the runner).
    Deletes are refused unless allow_deletes is set explicitly."""
    if name == "rest":
        from .adapters.rest_backend import RestFactoryBackend, RestTransport
        return RestFactoryBackend(RestTransport(url, key), folder or "", allow_deletes=allow_deletes)
    if name == "sdk":
        from .adapters.sdk_backend import SdkFactoryBackend
        return SdkFactoryBackend(url, key, folder or "", allow_deletes=allow_deletes)
    raise ValidationFailed(f"'{name}' is not a Factory API backend; use rest or sdk.")


def _github(settings: Settings):
    from .adapters.github import GitHubClient
    return GitHubClient(settings.github_repository, settings.github_token, api_url=settings.github_api_url)


def _dummy_tracker(settings: Settings):
    from .adapters import trackers
    return trackers.DummyWorkflowTracker(_github(settings), workflow=settings.dummy_workflow, ref=settings.github_ref,
                                         duration_seconds=settings.dummy_duration_seconds)


def _backend_and_tracker(settings: Settings, store, clock):
    from .adapters import trackers
    from .adapters.mock_backend import MockFactoryBackend

    allow_deletes = settings.deletes == "allow"
    if settings.executor == "github-runner":
        from .adapters.runner_backend import RunnerBackend
        github = _github(settings)
        backend = RunnerBackend(github, store, clock, workflow=settings.ops_workflow, ref=settings.github_ref,
                                backend=settings.backend, secret=settings.event_secrets[0],
                                request_ttl_seconds=settings.runner_timeout_seconds, allow_deletes=allow_deletes)
        tracker = trackers.RunnerJobTracker(backend, github)
    elif settings.backend == "mock":
        backend = MockFactoryBackend(store, clock=clock, review_ttl_seconds=settings.review_ttl_seconds)
        tracker = _dummy_tracker(settings) if settings.executor == "github-dummy" else trackers.InstantTracker()
        return backend, tracker  # the mock is a simulation already; AIF_DELETES governs the real API only
    else:
        backend = factory_api_backend(settings.backend, settings.factory_api_url, settings.factory_api_key,
                                      settings.factory_folder, allow_deletes=allow_deletes)
        tracker = _dummy_tracker(settings) if settings.executor == "github-dummy" else trackers.ApiJobTracker(backend)
    if settings.deletes == "simulate":
        from .adapters.simulated_deletes import CatalogMirror, DeleteRoutingTracker, DeleteSimulation
        simulator = MockFactoryBackend(CatalogMirror(backend.catalog_payload), clock=clock,
                                       review_ttl_seconds=settings.review_ttl_seconds)
        rehearsal = (_dummy_tracker(settings) if settings.github_repository and settings.github_token
                     else trackers.InstantTracker())
        return DeleteSimulation(backend, simulator), DeleteRoutingTracker(tracker, rehearsal)
    return backend, tracker


def build_runtime(env: Mapping[str, str] | None = None, *, vault=None) -> Runtime:
    env = os.environ if env is None else env
    if vault is None and env.get("AIF_KEY_VAULT_NAME"):
        from .adapters.keyvault import KeyVaultSecrets
        vault = KeyVaultSecrets(env["AIF_KEY_VAULT_NAME"])
    settings = Settings.from_env(env, vault=vault)
    clock = SystemClock()
    store = _store(settings)
    backend, tracker = _backend_and_tracker(settings, store, clock)
    service = LifecycleService(backend=backend, tracker=tracker, store=store,
                               guard=SelfProtection(settings.protected_ids), clock=clock,
                               poll_after_seconds=settings.poll_after_seconds,
                               github_repository=settings.github_repository,
                               runner_timeout_seconds=settings.runner_timeout_seconds)
    enqueue = None
    if settings.event_processing == "queue":
        from .adapters.queue import EventQueue
        enqueue = EventQueue(settings.queue_account, settings.event_queue).send
    return Runtime(settings=settings, service=service, api=LifecycleHttpApi(service, event_secrets=settings.event_secrets,
                                                                             enqueue=enqueue,
                                                                             required_role=settings.required_role))
