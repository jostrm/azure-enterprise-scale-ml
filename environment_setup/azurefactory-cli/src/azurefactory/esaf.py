"""ESAF - Enterprise Scale Azure Factory: the six scenario methods (Facade over AzureFactoryClient).

    from azurefactory import esaf

    esaf.init_factory(creation_request=body)              # Scenario 1: submit a server-owned full bootstrap
    esaf.add_scale_set("002", cidr="10.141.0.0/16")      # Scenario 2: register, enroll and deploy its common
    esaf.apply_project("002", scale_set="002")           # Scenario 3: add or update a project and deploy it
    esaf.delete_project("002")                           # Scenario 4
    esaf.delete_scale_set("002")                         # Scenario 5
    esaf.delete_factory()                                # Scenario 6

Connection: the environment variables AIFACTORY_API_URL, AIFACTORY_API_KEY and ESAF_FOLDER (the azurefactory folder
on the API host), or esaf.connect(folder=..., url=..., api_key=...). Each call prepares the server's review, checks
it, and confirms it at once: calling the method is the approval, so call it only for what you mean to change. It
returns an EsafJob after submission; job.wait() follows the server-side job to its end, or pass wait=True.
Select environment and scale_set explicitly when a suffix or project number is ambiguous. upsert_project remains
an alias-compatible entry point. Legacy init_factory(workflow_id/request=...) retains its client-side stage driver.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .client import AzureFactoryClient
from .errors import APIError, BlockedError, ConfigError, FailureError
from .review import validate_bindings, validate_preview
from .scale_set_enrollment import BLOB_BLOCKER

__all__ = ["connect", "init_factory", "add_scale_set", "apply_project", "upsert_project", "delete_project", "delete_scale_set",
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
            continuing = (self.kind == "workflow" and state.get("status") == "awaiting-review"
                          and state.get("requires_review") is False)
            if (state.get("status") not in ACTIVE and not continuing) or time.monotonic() > deadline:
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


def _scale(factory: dict, suffix: str | None, environment: str | None = None) -> dict | None:
    scales = [s for s in factory.get("scale_sets", [])
              if (suffix is None or s.get("suffix") == suffix)
              and (environment is None or s.get("environment") == environment)]
    if len(scales) > 1:
        raise ConfigError("Ambiguous scale set; select its environment and suffix explicitly.")
    return scales[0] if scales else None


def _project_scope(factory: dict, number: str, suffix: str | None = None,
                   environment: str | None = None) -> tuple[dict | None, dict | None]:
    if suffix is not None:
        _scale(factory, suffix, environment)
    matches = [(p, scale) for p in factory.get("projects", []) if p.get("number") == number
               for placement in p.get("placements", [])
               for scale in factory.get("scale_sets", [])
               if placement.get("scale_set_id") == scale.get("id")
               and placement.get("environment") == scale.get("environment")
               and (suffix is None or scale.get("suffix") == suffix)
               and (environment is None or scale.get("environment") == environment)]
    if len(matches) > 1:
        raise ConfigError("Ambiguous project " + number + "; select its environment and scale_set explicitly.")
    if matches:
        return matches[0]
    return None, _scale(factory, suffix, environment)


def _refresh_scope(s: Session, factory: dict, scale: dict,
                   project: dict | None = None) -> tuple[dict, dict, dict, dict | None]:
    """Refresh revisions without changing the exact target selected before a configuration write."""
    document, current = _catalog(s)
    if current["id"] != factory["id"]:
        raise ConfigError("The selected factory changed during the operation.")
    if project is None:
        selected = _scale(current, scale["suffix"], scale["environment"])
        selected_project = None
    else:
        selected_project, selected = _project_scope(current, project["number"], scale["suffix"], scale["environment"])
        if selected_project is None or selected_project["id"] != project["id"]:
            raise ConfigError("The selected project placement changed during the operation.")
    if selected is None or selected["id"] != scale["id"]:
        raise ConfigError("The selected scale set changed during the operation.")
    return document, current, selected, selected_project


def _field(review: dict, key: str):
    preview = review.get("preview") if isinstance(review.get("preview"), dict) else {}
    return review.get(key, preview.get(key))


def _blockers(review: dict) -> list:
    return list(_field(review, "blockers") or [])


def _require(review: dict, what: str) -> dict:
    if _field(review, "can_execute") is not True or _blockers(review):
        raise BlockedError(what + " was refused: " + "; ".join(map(str, _blockers(review) or ["no executable review"])))
    return review


def _already(text: str) -> bool:
    return any(marker in text for marker in _ALREADY)


def _confirm(s: Session, review: dict, what: str) -> dict:
    return s.client.catalog_confirm(s.folder, _require(review, what)["confirmation_id"])


def _job(s: Session, scenario: str, confirmed: dict, wait: bool, kind: str = "catalog") -> EsafJob:
    job = confirmed.get("job")
    identifier = _identifier(job.get("id") if isinstance(job, dict) else None, "job")
    handle = EsafJob(scenario, kind, identifier, s)
    if wait:
        handle.wait()
    return handle


def _identifier(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FailureError("The API returned no valid " + what + " ID; inspect server state before retrying.")
    return value


def _require_project_runtime_scope(review: dict, factory: dict, scale: dict, project: dict, *,
                                   deleting: bool = False) -> None:
    _require(review, "delete project" if deleting else "project deploy")
    proof = _field(review, "runtime_scope_authorization")
    if not isinstance(proof, dict):
        raise BlockedError("Project runtime review is missing live scope authorization; use a supporting Factory API.")
    expected = {"factory_id": factory["id"], "scale_set_id": scale["id"], "project_id": project["id"]}
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ConfigError("Project runtime authorization does not match the exact selected factory, scale set and project.")
    if proof.get("enrolled") is not True:
        raise BlockedError("Project runtime authorization does not prove live enrollment of the selected project.")
    if type(proof.get("delete_authorized")) is not bool:
        raise ConfigError("Project runtime authorization must report an explicit live deletion permission.")
    if deleting and proof["delete_authorized"] is not True:
        raise BlockedError("Project deletion is not authorized by the live runtime scope.")
    group = proof.get("resource_group_id")
    match = re.fullmatch(r"/subscriptions/([^/]+)/resourcegroups/([\w().-]{1,90})", group) if isinstance(group, str) else None
    try:
        subscription = UUID(match[1]) if match else None
        valid = (match and group == group.lower() and not match[2].endswith(".")
                 and subscription.int and str(subscription) == match[1]
                 and subscription == UUID(scale.get("subscription_id")))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ConfigError("Project runtime authorization must name a normalized resource-group ARM ID "
                          "in the selected scale set's subscription.")


def _deploy(s: Session, document: dict, factory: dict, scale: dict, project: dict | None, version_ref: str | None,
            wait: bool, scenario: str) -> EsafJob:
    body = {"folder": s.folder, "contract_version": 1, "action": "deploy", "expected_revision": document["revision"],
            "factory_id": factory["id"], "scale_set_id": scale["id"], "project_id": project["id"] if project else None,
            "version_ref": version_ref or factory.get("aifactory_version") or factory.get("version_ref")}
    review = s.client.catalog_prepare(body)
    if project is not None:
        _require_project_runtime_scope(review, factory, scale, project)
    return _job(s, scenario, _confirm(s, review, scenario + " deploy"), wait)


def _allow_deletion(s: Session, factory: dict) -> None:
    """Grant single-writer permission; Blob deletion still requires its protected runtime review."""
    try:
        review = s.client.authorize_deletion_prepare({"contract_version": 1, "folder": s.folder,
                                                       "factory_id": factory["id"], "mode": "allow"})
    except APIError as error:
        if _already(str(error)):
            return
        raise
    if _field(review, "can_execute") is False and _blockers(review) == [BLOB_BLOCKER]:
        return
    blockers = _blockers(review)
    if _field(review, "can_execute") is False and blockers and all(_already(str(b)) for b in blockers):
        return
    _require(review, "authorize deletion")
    s.client.authorize_deletion_confirm(folder=s.folder, confirmation_id=_field(review, "confirmation_id"),
                                        preview_hash=_field(review, "preview_hash"),
                                        confirmation_phrase=_field(review, "confirmation_phrase"))


def _enroll_scale(s: Session, document: dict, factory: dict, scale: dict,
                  project: dict | None = None) -> tuple[dict, dict, dict, dict | None]:
    review = s.client.enroll_scale_set_prepare({"contract_version": 1, "folder": s.folder,
                                                "factory_id": factory["id"], "scale_set_id": scale["id"]})
    if (_field(review, "can_execute") is False
            and _blockers(review) in (
                [BLOB_BLOCKER], ["The selected scale set already has a binding target."],
                ["The scale set already has a binding target; it is enrolled. Nothing was changed."])):
        return document, factory, scale, project
    _require(review, "enroll scale set")
    confirmed = s.client.enroll_scale_set_confirm(
        folder=s.folder, confirmation_id=_field(review, "confirmation_id"),
        preview_hash=_field(review, "preview_hash"), confirmation_phrase=_field(review, "confirmation_phrase"))
    if confirmed.get("status") not in ("enrolled", "binding-repaired"):
        raise FailureError("Scale-set enrollment failed: " + str(confirmed.get("message") or confirmed))
    return _refresh_scope(s, factory, scale, project)


def _validate_workflow_review(request: dict, review: dict) -> None:
    preview_scope = review.get("scope")
    details = review.get("review")
    authorization = details.get("workflow_authorization") if isinstance(details, dict) else None
    authorized_scope = authorization.get("scope") if isinstance(authorization, dict) else None
    scope = request["scope"]
    if (scope.get("project_id") is None and isinstance(preview_scope, dict) and isinstance(authorized_scope, dict)
            and {**preview_scope, "project_id": preview_scope.get("project_id")} == scope
            and {**authorized_scope, "project_id": authorized_scope.get("project_id")} == scope):
        # Null and omission name the same common-only scope. Never change the signed manifest or its hash.
        request = {**request, "scope": authorized_scope}
        review = {**review, "scope": authorized_scope}
    validate_bindings(request, review, "creation-workflow-start", "creation-workflow")
    validate_preview(review)


def _create_factory(s: Session, creation_request: dict, wait: bool, poll: float) -> EsafJob:
    config = creation_request.get("config")
    if (creation_request.get("mode") != "full-bootstrap" or creation_request.get("contract_version") != 1
            or not isinstance(config, dict)
            or any(not isinstance(config.get(key), str) or not config[key].strip()
                   for key in ("factory_prefix", "location", "scale_set_number"))):
        raise ConfigError("creation_request must describe a full-bootstrap with factory_prefix, location and "
                          "scale_set_number in config.")
    initial = creation_request.get("initial_project", {"number": config.get("project_number", "001")})
    if initial is not None and not isinstance(initial, dict):
        raise ConfigError("initial_project must be an object or null (common-only).")
    review = _require(s.client.creation_prepare(creation_request), "create factory")
    if _field(review, "folder") != s.folder:
        raise ConfigError("Creation review changed the session's azurefactory folder.")
    confirmed = s.client.creation_confirm(s.folder, _identifier(_field(review, "confirmation_id"), "confirmation"))
    document = confirmed.get("catalog")
    if not isinstance(document, dict) or "factories" not in document:
        document = s.client.catalog_list(s.folder)
    factories = [factory for factory in document.get("factories", [])
                 if factory.get("prefix") == config["factory_prefix"] and factory.get("region") == config["location"]
                 and (s.factory is None or s.factory in (factory.get("id"), factory.get("key")))]
    if len(factories) != 1:
        raise ConfigError("Cannot identify the exact newly created factory in the catalog.")
    factory = factories[0]
    scale = _scale(factory, config["scale_set_number"], "dev")
    if scale is None:
        raise ConfigError("The newly created dev scale set is not registered.")
    project = None
    if initial is not None:
        project, _ = _project_scope(factory, initial.get("number", "001"), scale["suffix"], "dev")
        if project is None:
            raise ConfigError("The requested initial project is not registered on the newly created dev scale set.")
    scope = {"folder": s.folder, "factory_id": _identifier(factory.get("id"), "factory"),
             "scale_set_id": _identifier(scale.get("id"), "scale set"),
             "project_id": _identifier(project.get("id"), "project") if project is not None else None}
    request = {"contract_version": 1, "operation": "create-factory", "execution_mode": "privileged-bootstrap",
               "creation_mode": "full-bootstrap", "scope": scope,
               "expected_revision": _identifier(document.get("revision") or document.get("source_revision"), "catalog revision"),
               "bootstrap_config": config, "approval_mode": "whole-workflow", "authorization_valid_for_seconds": 21600}
    review = _require(s.client.creation_workflow_prepare(request), "create factory workflow")
    _validate_workflow_review(request, review)
    workflow_id = review["workflow_id"]
    started = s.client.creation_workflow_start(
        s.folder, workflow_id, review["confirmation_id"],
        authorization_hash=review["review"]["workflow_authorization"]["authorization_hash"])
    if (started.get("workflow_id", workflow_id) != workflow_id
            or started.get("status") not in ACTIVE | {"awaiting-review", "succeeded"}
            or started.get("requires_review") is True):
        raise FailureError("Creation workflow submission failed: "
                           + str(started.get("message") or started.get("blockers") or started))
    handle = EsafJob("init_factory", "workflow", workflow_id, s)
    if wait:
        handle.wait(poll=poll)
    return handle


# The six scenarios -------------------------------------------------------------------------------------------------
def init_factory(workflow_id: str | None = None, *, request: dict | None = None,
                 creation_request: dict | None = None, wait: bool = False,
                 poll: float = 30, session: Session | None = None) -> EsafJob:
    """Scenario 1: save and submit a full bootstrap with creation_request (one server-owned approval).

    creation_request is the creation API body, whose folder is the consumer repository root; session.folder is
    its azurefactory folder. request= and workflow_id retain the legacy client-side per-stage driver.
    """
    s = _session(session)
    if creation_request is not None:
        if workflow_id is not None or request is not None:
            raise ConfigError("Use creation_request alone, not with request or workflow_id.")
        return _create_factory(s, creation_request, wait, poll)
    if workflow_id is None:
        if request is None:
            raise ConfigError("init_factory needs the workflow_id to resume, or request= for a new creation workflow.")
        workflow_id = s.client.creation_workflow_prepare(request).get("workflow_id")
    workflow_id = _identifier(workflow_id, "workflow")
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
    if _scale(factory, suffix, environment) is None:
        like = next((x for x in factory.get("scale_sets", []) if x.get("environment") == environment),
                    next(iter(factory.get("scale_sets", [])), {}))
        added = {"environment": environment, "suffix": suffix,
                 "tenant_id": tenant_id or like.get("tenant_id"),
                 "subscription_id": subscription_id or like.get("subscription_id"),
                 "orchestrator": orchestrator or like.get("orchestrator"),
                 "network": {"vnet_cidr": cidr, "max_projects": max_projects}}
        review = s.client.scaleset_add_prepare(s.folder, factory["id"], [added], expected_revision=document["revision"])
        _confirm(s, review, "add scale set")
        document, current = _catalog(s)
        if current["id"] != factory["id"]:
            raise ConfigError("The selected factory changed during the operation.")
        factory = current
    scale = _scale(factory, suffix, environment)
    if scale is None:
        raise ConfigError("Scale set " + suffix + " is not registered in " + environment + ".")
    document, factory, scale, _ = _enroll_scale(s, document, factory, scale)
    return _deploy(s, document, factory, scale, None, version_ref, wait, "add_scale_set")


def upsert_project(number: str, *, scale_set: str | None = None, environment: str | None = None,
                   settings: dict | None = None,
                   display_name: str = "", version_ref: str | None = None, wait: bool = False,
                   session: Session | None = None) -> EsafJob:
    """Scenario 3: add/update a project, refresh its scale set's enrollment, then deploy the selected placement.

    Enrollment covers the common resource group and every project already placed on this scale set when the API
    supports extending its enrollment. A no-op is not proof of coverage: the protected deploy review must still
    verify the exact project. Blob coordination needs no enrollment through the single-writer operation.
    """
    s = _session(session)
    document, factory = _catalog(s)
    project, scale = _project_scope(factory, number, scale_set, environment)
    if scale is None:
        raise ConfigError("Scale set " + str(scale_set) + " is not registered; run esaf.add_scale_set first.")
    if project is None:
        review = s.client.project_add_prepare(
            s.folder, factory["id"], number=number, display_name=display_name,
            placements=[{"environment": scale["environment"], "scale_set_id": scale["id"]}],
            expected_revision=document["revision"])
        _confirm(s, review, "add project")
        document, factory, scale, _ = _refresh_scope(s, factory, scale)
        project, _ = _project_scope(factory, number, scale["suffix"], scale["environment"])
        if project is None:
            raise ConfigError("Project " + number + " was not registered on the selected scale set.")
    if settings:
        review = s.client.catalog_settings_prepare(s.folder, factory["id"], settings, scale_set_id=scale["id"],
                                                   project_id=project["id"], expected_revision=document["revision"])
        _confirm(s, review, "project settings")
        document, factory, scale, project = _refresh_scope(s, factory, scale, project)
    document, factory, scale, project = _enroll_scale(s, document, factory, scale, project)
    return _deploy(s, document, factory, scale, project, version_ref, wait, "upsert_project")


apply_project = upsert_project


def delete_project(number: str, *, scale_set: str | None = None, environment: str | None = None,
                   include_project_subnets: bool = False,
                   include_keyvault_and_resource_group: bool = True, version_ref: str | None = None,
                   wait: bool = False, session: Session | None = None) -> EsafJob:
    """Scenario 4: delete project <number>'s resources (its resource group by default)."""
    s = _session(session)
    _, factory = _catalog(s)
    project, scale = _project_scope(factory, number, scale_set, environment)
    if project is None or scale is None:
        raise ConfigError("Project " + number + " is not registered on the selected scale set.")
    _allow_deletion(s, factory)
    document, factory, scale, project = _refresh_scope(s, factory, scale, project)
    review = s.client.project_delete_prepare(
        s.folder, factory["id"], project["id"], environments=[scale["environment"]],
        include_project_subnets=include_project_subnets,
        include_keyvault_and_resource_group=include_keyvault_and_resource_group,
        expected_revision=document["revision"], scale_set_id=scale["id"], version_ref=version_ref)
    _require_project_runtime_scope(review, factory, scale, project, deleting=True)
    return _job(s, "delete_project", _confirm(s, review, "delete project"), wait)


def delete_scale_set(suffix: str, *, environment: str | None = None,
                     version_ref: str | None = None, wait: bool = False,
                     session: Session | None = None) -> EsafJob:
    """Scenario 5: delete scale set <suffix>'s registered resources."""
    s = _session(session)
    _, factory = _catalog(s)
    scale = _scale(factory, suffix, environment)
    if scale is None:
        raise ConfigError("Scale set " + suffix + " is not registered.")
    _allow_deletion(s, factory)
    document, factory, scale, _ = _refresh_scope(s, factory, scale)
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
