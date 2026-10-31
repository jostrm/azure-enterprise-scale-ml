"""ESAF - Enterprise Scale Azure Factory: the six scenario methods (Facade over AzureFactoryClient).

    from azurefactory import esaf

    esaf.init_factory(workflow_id)                       # Scenario 1: drive a creation workflow to the end
    esaf.add_scale_set("002", cidr="10.141.0.0/16")      # Scenario 2: register, enroll and deploy its common
    esaf.upsert_project("002", scale_set="002")          # Scenario 3: add or update a project and deploy it
    esaf.delete_project("002")                           # Scenario 4
    esaf.delete_scale_set("002")                         # Scenario 5
    esaf.delete_factory()                                # Scenario 6

Connection: the environment variables AIFACTORY_API_URL, AIFACTORY_API_KEY and ESAF_FOLDER (the azurefactory folder
on the API host), or esaf.connect(folder=..., url=..., api_key=...). Each call prepares the server's review, checks
it, and confirms it at once: calling the method is the approval, so call it only for what you mean to change. It
returns an EsafJob immediately (fire and forget); job.wait() follows the server-side job to its end, or pass
wait=True. Defaults (subscription, tenant, orchestrator, version, environment) come from the factory itself.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .client import AzureFactoryClient
from .errors import APIError, BlockedError, ConfigError

__all__ = ["connect", "init_factory", "add_scale_set", "upsert_project", "delete_project", "delete_scale_set",
           "delete_factory", "EsafJob", "Session"]

ACTIVE = {"queued", "running", "pending"}
_ALREADY = ("already has a binding target", "Nothing to change", "already allowed")


@dataclass
class Session:
    folder: str
    client: Any
    factory: str | None = None  # factory key or id; default: the folder's only factory


_default: Session | None = None


def connect(folder: str | None = None, url: str | None = None, api_key: str | None = None, *,
            factory: str | None = None, client: Any = None) -> Session:
    """Connect once; every scenario method uses this session unless one is passed."""
    global _default
    folder = folder or os.environ.get("ESAF_FOLDER")
    if not folder:
        raise ConfigError("Set ESAF_FOLDER (the azurefactory folder on the API host) or call esaf.connect(folder=...).")
    if client is None:
        client = AzureFactoryClient(base_url=url, api_key=api_key,
                                    timeout=float(os.environ.get("ESAF_TIMEOUT", "1800")))
    _default = Session(folder, client, factory)
    return _default


@dataclass
class EsafJob:
    """A started scenario. status() reads it once; wait() follows it to its end."""
    scenario: str
    kind: str  # catalog | factory-deletion | workflow
    id: str | None
    session: Session
    result: dict | None = None
    _thread: threading.Thread | None = field(default=None, repr=False)

    def status(self) -> dict:
        client, folder = self.session.client, self.session.folder
        if self.kind == "catalog":
            state = client.catalog_job(folder, self.id)
        elif self.kind == "factory-deletion":
            state = client.delete_aifactory_status(folder, self.id)
        else:
            state = client.creation_workflow_status(folder, self.id)
        return state["job"] if isinstance(state.get("job"), dict) else state

    def wait(self, timeout: float = 8 * 3600, poll: float = 30) -> dict:
        if self._thread is not None:
            self._thread.join(timeout)
            return self.result
        deadline = time.monotonic() + timeout
        while True:
            state = self.status()
            if state.get("status") not in ACTIVE or time.monotonic() > deadline:
                self.result = state
                return state
            time.sleep(poll)


# Private helpers ---------------------------------------------------------------------------------------------------
def _session(session: Session | None) -> Session:
    return session or _default or connect()


def _catalog(s: Session) -> tuple[dict, dict]:
    document = s.client.catalog_list(s.folder)
    factories = document.get("factories", [])
    if s.factory:
        matches = [f for f in factories if s.factory in (f.get("id"), f.get("key"))]
    else:
        matches = factories
    if len(matches) != 1:
        raise ConfigError("Select the factory with esaf.connect(factory=<key>); the folder has "
                          + str(len(factories)) + " factories.")
    return document, matches[0]


def _scale(factory: dict, suffix: str | None) -> dict | None:
    scales = factory.get("scale_sets", [])
    if suffix is None:
        return scales[0] if scales else None
    return next((s for s in scales if s.get("suffix") == suffix), None)


def _project(factory: dict, number: str) -> dict | None:
    return next((p for p in factory.get("projects", []) if p.get("number") == number), None)


def _field(review: dict, key: str):
    preview = review.get("preview") if isinstance(review.get("preview"), dict) else {}
    return review.get(key, preview.get(key))


def _blockers(review: dict) -> list:
    return list(_field(review, "blockers") or [])


def _require(review: dict, what: str) -> dict:
    if _field(review, "can_execute") is not True:
        raise BlockedError(what + " was refused: " + "; ".join(map(str, _blockers(review) or ["no executable review"])))
    return review


def _already(text: str) -> bool:
    return any(marker in text for marker in _ALREADY)


def _confirm(s: Session, review: dict, what: str) -> dict:
    return s.client.catalog_confirm(s.folder, _require(review, what)["confirmation_id"])


def _job(s: Session, scenario: str, confirmed: dict, wait: bool, kind: str = "catalog") -> EsafJob:
    job = confirmed.get("job") or {}
    handle = EsafJob(scenario, kind, job.get("id"), s)
    if wait and handle.id:
        handle.wait()
    return handle


def _deploy(s: Session, document: dict, factory: dict, scale: dict, project: dict | None, version_ref: str | None,
            wait: bool, scenario: str) -> EsafJob:
    body = {"folder": s.folder, "contract_version": 1, "action": "deploy", "expected_revision": document["revision"],
            "factory_id": factory["id"], "scale_set_id": scale["id"], "project_id": project["id"] if project else None,
            "version_ref": version_ref or factory.get("aifactory_version") or factory.get("version_ref")}
    review = s.client.catalog_prepare(body)
    return _job(s, scenario, _confirm(s, review, scenario + " deploy"), wait)


def _allow_deletion(s: Session, factory: dict) -> None:
    """Grant the factory's deletion permission once; already allowed is not a failure (idempotent)."""
    try:
        review = s.client.authorize_deletion_prepare({"contract_version": 1, "folder": s.folder,
                                                       "factory_id": factory["id"], "mode": "allow"})
    except APIError as error:
        if _already(str(error)):
            return
        raise
    if _field(review, "can_execute") is not True and any(_already(str(b)) for b in _blockers(review)):
        return
    _require(review, "authorize deletion")
    s.client.authorize_deletion_confirm(folder=s.folder, confirmation_id=_field(review, "confirmation_id"),
                                        preview_hash=_field(review, "preview_hash"),
                                        confirmation_phrase=_field(review, "confirmation_phrase"))


# The six scenarios -------------------------------------------------------------------------------------------------
def init_factory(workflow_id: str | None = None, *, request: dict | None = None, wait: bool = False,
                 poll: float = 30, session: Session | None = None) -> EsafJob:
    """Scenario 1: drive a creation workflow through every stage (new with request=..., or resume workflow_id)."""
    s = _session(session)
    if workflow_id is None:
        if request is None:
            raise ConfigError("init_factory needs the workflow_id to resume, or request= for a new creation workflow.")
        workflow_id = s.client.creation_workflow_prepare(request)["workflow_id"]
    handle = EsafJob("init_factory", "workflow", workflow_id, s)

    def drive():
        while True:
            state = s.client.creation_workflow_status(s.folder, workflow_id)
            while state.get("status") in ACTIVE:
                time.sleep(poll)
                state = s.client.creation_workflow_status(s.folder, workflow_id)
            if state.get("status") not in ("awaiting-review", "blocked"):
                handle.result = state
                return
            review = s.client.creation_workflow_next(s.folder, workflow_id)
            if _field(review, "can_execute") is not True:
                handle.result = {**state, "status": "blocked", "blockers": _blockers(review)}
                return
            s.client.creation_workflow_start(s.folder, workflow_id, review["confirmation_id"])

    if wait:
        drive()
    else:
        handle._thread = threading.Thread(target=drive, name="esaf-init-factory", daemon=True)
        handle._thread.start()
    return handle


def add_scale_set(suffix: str, cidr: str, *, environment: str = "dev", max_projects: int = 3,
                  subscription_id: str | None = None, tenant_id: str | None = None, orchestrator: str | None = None,
                  version_ref: str | None = None, wait: bool = False, session: Session | None = None) -> EsafJob:
    """Scenario 2: register scale set <suffix> (if new), enroll it and deploy its common."""
    s = _session(session)
    document, factory = _catalog(s)
    if _scale(factory, suffix) is None:
        like = next((x for x in factory.get("scale_sets", []) if x.get("environment") == environment),
                    _scale(factory, None)) or {}
        added = {"environment": environment, "suffix": suffix,
                 "tenant_id": tenant_id or like.get("tenant_id"),
                 "subscription_id": subscription_id or like.get("subscription_id"),
                 "orchestrator": orchestrator or like.get("orchestrator"),
                 "network": {"vnet_cidr": cidr, "max_projects": max_projects}}
        review = s.client.scaleset_add_prepare(s.folder, factory["id"], [added], expected_revision=document["revision"])
        _confirm(s, review, "add scale set")
        document, factory = _catalog(s)
    scale = _scale(factory, suffix)
    review = s.client.enroll_scale_set_prepare({"contract_version": 1, "folder": s.folder,
                                                "factory_id": factory["id"], "scale_set_id": scale["id"]})
    if not (_field(review, "can_execute") is not True and any(_already(str(b)) for b in _blockers(review))):
        _require(review, "enroll scale set")
        s.client.enroll_scale_set_confirm(folder=s.folder, confirmation_id=_field(review, "confirmation_id"),
                                          preview_hash=_field(review, "preview_hash"),
                                          confirmation_phrase=_field(review, "confirmation_phrase"))
        document, factory = _catalog(s)
        scale = _scale(factory, suffix)
    return _deploy(s, document, factory, scale, None, version_ref, wait, "add_scale_set")


def upsert_project(number: str, *, scale_set: str | None = None, settings: dict | None = None,
                   display_name: str = "", version_ref: str | None = None, wait: bool = False,
                   session: Session | None = None) -> EsafJob:
    """Scenario 3: add project <number> (placed on scale_set, default the first) or update it, then deploy it."""
    s = _session(session)
    document, factory = _catalog(s)
    project = _project(factory, number)
    if project is None:
        scale = _scale(factory, scale_set)
        if scale is None:
            raise ConfigError("Scale set " + str(scale_set) + " is not registered; run esaf.add_scale_set first.")
        review = s.client.project_add_prepare(
            s.folder, factory["id"], number=number, display_name=display_name,
            placements=[{"environment": scale["environment"], "scale_set_id": scale["id"]}],
            expected_revision=document["revision"])
        _confirm(s, review, "add project")
        document, factory = _catalog(s)
        project = _project(factory, number)
    placed = {item["scale_set_id"] for item in project.get("placements", [])}
    scale = _scale(factory, scale_set) if scale_set else next(
        (x for x in factory.get("scale_sets", []) if x["id"] in placed), None)
    if scale is None or scale["id"] not in placed:
        raise ConfigError("Project " + number + " is not placed on scale set " + str(scale_set) + ".")
    if settings:
        review = s.client.catalog_settings_prepare(s.folder, factory["id"], settings, scale_set_id=scale["id"],
                                                   project_id=project["id"], expected_revision=document["revision"])
        _confirm(s, review, "project settings")
        document, factory = _catalog(s)
    return _deploy(s, document, factory, scale, project, version_ref, wait, "upsert_project")


def delete_project(number: str, *, include_project_subnets: bool = False,
                   include_keyvault_and_resource_group: bool = True, version_ref: str | None = None,
                   wait: bool = False, session: Session | None = None) -> EsafJob:
    """Scenario 4: delete project <number>'s resources (its resource group by default)."""
    s = _session(session)
    _, factory = _catalog(s)
    _allow_deletion(s, factory)
    document, factory = _catalog(s)
    project = _project(factory, number)
    if project is None:
        raise ConfigError("Project " + number + " is not registered.")
    placement = project["placements"][0]
    review = s.client.project_delete_prepare(
        s.folder, factory["id"], project["id"], environments=[placement["environment"]],
        include_project_subnets=include_project_subnets,
        include_keyvault_and_resource_group=include_keyvault_and_resource_group,
        expected_revision=document["revision"], scale_set_id=placement["scale_set_id"], version_ref=version_ref)
    return _job(s, "delete_project", _confirm(s, review, "delete project"), wait)


def delete_scale_set(suffix: str, *, version_ref: str | None = None, wait: bool = False,
                     session: Session | None = None) -> EsafJob:
    """Scenario 5: delete scale set <suffix>'s registered resources."""
    s = _session(session)
    _, factory = _catalog(s)
    _allow_deletion(s, factory)
    document, factory = _catalog(s)
    scale = _scale(factory, suffix)
    if scale is None:
        raise ConfigError("Scale set " + suffix + " is not registered.")
    review = s.client.scaleset_delete_prepare(s.folder, factory["id"], scale["id"],
                                              expected_revision=document["revision"], version_ref=version_ref)
    return _job(s, "delete_scale_set", _confirm(s, review, "delete scale set"), wait)


def delete_factory(*, version_ref: str | None = None, wait: bool = False,
                   session: Session | None = None) -> EsafJob:
    """Scenario 6: delete the whole factory (every registered resource; shared hubs and subscriptions stay)."""
    s = _session(session)
    _, factory = _catalog(s)
    _allow_deletion(s, factory)
    document, factory = _catalog(s)
    body = {"contract_version": 1, "folder": s.folder, "factory_id": factory["id"],
            "expected_revision": document["revision"]}
    if version_ref:
        body["version_ref"] = version_ref
    review = _require(s.client.delete_aifactory_prepare(body), "delete factory")
    confirmed = s.client.delete_aifactory_confirm(
        folder=s.folder, confirmation_id=_field(review, "confirmation_id"),
        preview_hash=_field(review, "preview_hash"), confirmation_phrase=_field(review, "confirmation_phrase"))
    return _job(s, "delete_factory", confirmed, wait, kind="factory-deletion")
