"""A loopback fake of the Factory API that records every call (the faked transport for the parity test)."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

REVISION = "a" * 64
FACTORY_ID = "11111111-1111-4111-8111-111111111111"
SCALESET_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
JOB_ID = "44444444-4444-4444-8444-444444444444"
WORKFLOW_ID = "55555555-5555-4555-8555-555555555555"
CONFIRMATION_ID = "66666666-6666-4666-8666-666666666666"
AUTHORIZATION_HASH = "c" * 64

CATALOG = {"contract_version": 1, "mode": "catalog", "revision": REVISION, "factories": [{
    "id": FACTORY_ID, "key": "aif-121-swedencentral", "kind": "ai", "prefix": "aif-121-", "region": "swedencentral",
    "region_short_name": "sdc",
    "scale_sets": [{"id": SCALESET_ID, "environment": "dev", "suffix": "001", "status": "configured"}],
    "projects": [{"id": PROJECT_ID, "key": "project-001-001", "number": "001", "display_name": "Project 001",
                  "placements": [{"environment": "dev", "scale_set_id": SCALESET_ID}]}],
}]}

PREVIEW = {"contract_version": 1, "confirmation_id": CONFIRMATION_ID, "can_execute": False, "summary": "Review",
           "effects": ["Deploy aif-121-esml-common-sdc-dev-001"], "warnings": [], "blockers": ["Fake API"],
           "expires_at": "2026-10-21T12:10:00Z", "source_revision": REVISION, "operation_mode": "runtime",
           "preview_hash": "b" * 64, "confirmation_phrase": "DELETE aif-121-swedencentral",
           "workflow_id": WORKFLOW_ID,
           "deletion_targets": [{"resource_group": "aif-121-esml-common-sdc-dev-001"}]}

JOB = {"id": JOB_ID, "action": "deploy", "status": "queued", "message": "", "factory_id": FACTORY_ID,
       "created_at": "2026-10-21T12:00:00Z", "updated_at": "2026-10-21T12:00:00Z", "pipeline_runs": []}

OPENAPI = {"openapi": "3.1.0", "components": {"schemas": {"CatalogPrepare": {"properties": {
    "initial_project": {}, "target_region_short_name": {}}}}}}

SUBSCRIPTION_ID = "f0fe8b33-73bf-41e4-9997-e3920d793c06"
ENROLL_PREPARE = "/api/v1/operations/enroll-scale-set/prepare"
ENROLL_CONFIRM = "/api/v1/operations/enroll-scale-set/confirm"
ENROLL_PHRASE = "ENROLL SCALE SET aif-121 002"
BLOB_BLOCKER = "Blob-coordinated factories are not supported yet; nothing was changed."
CONTRIBUTOR = "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
RBAC_ADMIN = "/providers/Microsoft.Authorization/roleDefinitions/f58310d9-a9f6-439a-9e8d-f62e7b41a168"


def group_id(name: str) -> str:
    return f"/subscriptions/{SUBSCRIPTION_ID}/resourcegroups/{name}"


def enroll_preview(body: dict, groups: list[str], *, phrase: str = ENROLL_PHRASE, blockers=(),
                   confirmation_id: str = CONFIRMATION_ID, creations=None) -> dict:
    """Pink's enroll-scale-set review (capability enroll-scale-set-v1) for the requested scale set."""
    ids = [group_id(name) for name in groups]
    creations = ids[:1] if creations is None else creations
    assignments = [{"scope": scope, "role_definition_id": role, "assignment_id": f"{index}-{role[-4:]}",
                    "exists": False} for index, scope in enumerate(ids) for role in (CONTRIBUTOR, RBAC_ADMIN)]
    blocked = bool(blockers)
    return {"contract_version": 1, "capabilities": ["enroll-scale-set-v1"], "operation_mode": "provider-state-and-arm",
            "azure_writes": not blocked, "can_execute": not blocked, "folder": body["folder"],
            "factory_id": body["factory_id"], "scale_set_id": body["scale_set_id"],
            "repository": None if blocked else "jostrm/azure-enterprise-scale-byor-121",
            "state_ref": "refs/heads/aifactory-state/single-writer-v1",
            "provider_head": None if blocked else "d" * 40, "writer_id": None if blocked else "gha-aif-121",
            "auth_namespace": None if blocked else "aif-121",
            "deployment_object_id": None if blocked else "77777777-7777-4777-8777-777777777777",
            "subscription_id": SUBSCRIPTION_ID, "resource_group_ids": [] if blocked else ids,
            "common_dependency_ids": [], "resource_group_creations": [] if blocked else creations,
            "role_assignments": [] if blocked else assignments,
            "enrollment_revision": {"from": None, "to": None} if blocked else {"from": 1, "to": 2},
            "coordination_hash": {"from": None, "to": None} if blocked else {"from": "h1", "to": "h2"},
            "bindings": [] if blocked else ["gha"], "warnings": [], "blockers": list(blockers),
            "confirmation_id": confirmation_id, "preview_hash": "e" * 64, "confirmation_phrase": phrase,
            "audit_record": f"scale-set-enrollments/{body['factory_id']}/{confirmation_id}.json",
            "expires_at": "2026-10-21T12:10:00Z"}


def enroll_result(preview: dict) -> dict:
    return {"contract_version": 1, "status": "enrolled", "folder": preview["folder"],
            "factory_id": preview["factory_id"], "scale_set_id": preview["scale_set_id"],
            "repository": preview["repository"], "state_ref": preview["state_ref"],
            "previous_head": preview["provider_head"], "head": "f" * 40, "audit_record": preview["audit_record"],
            "resource_group_ids": preview["resource_group_ids"],
            "resource_groups_created": preview["resource_group_creations"],
            "role_assignments_created": [item["assignment_id"] for item in preview["role_assignments"]],
            "bindings_updated": preview["bindings"], "message": "The scale set is enrolled."}


FIXED_ENROLL_GROUPS = ["aif-121-esml-common-sdc-dev-002", "aif-121-esml-project001-sdc-dev-002-rg"]


def _response(method: str, path: str, body):
    if path == "/openapi.json":
        return OPENAPI
    if path == ENROLL_PREPARE:
        return enroll_preview(body, FIXED_ENROLL_GROUPS)
    if path == ENROLL_CONFIRM:
        return enroll_result(enroll_preview({"folder": body["folder"], "factory_id": FACTORY_ID,
                                             "scale_set_id": SCALESET_ID}, FIXED_ENROLL_GROUPS))
    if method == "GET" and path == "/api/v1/factory-catalog":
        return CATALOG
    if method == "GET" and path.startswith("/api/v1/factory-catalog/jobs/"):
        return JOB
    if method == "GET" and path.startswith("/api/v1/creation/workflows/"):
        return {"workflow_id": WORKFLOW_ID, "status": "running"}
    if path == "/api/v1/creation/prepare":  # ConfigurationPreview: the catalog review plus the folder it resolved
        return {**PREVIEW, "folder": body["folder"]}
    if path == "/api/v1/creation/confirm":
        return {"contract_version": 1, "catalog": CATALOG, "job": None}
    if path == "/api/v1/creation/workflows/prepare":
        return {**PREVIEW, "review": {"workflow_authorization": {"authorization_hash": AUTHORIZATION_HASH}}}
    if path in ("/api/v1/factory-catalog/prepare", "/api/v1/operations/delete-aifactory/prepare"):
        return PREVIEW
    if path in ("/api/v1/factory-catalog/confirm", "/api/v1/operations/delete-aifactory/confirm"):
        return {"contract_version": 1, "catalog": CATALOG, "job": JOB}
    if path == "/api/v1/creation/workflows/start":
        return {"workflow_id": WORKFLOW_ID, "status": "running"}
    return None


class Refused(Exception):
    """The API's 409 answer (a pink CatalogError) with its detail."""


class StatefulCatalog:
    """Pink's catalog prepare/confirm semantics (Factory API v0.47.45, src/factory_catalog.py) for the one factory.

    A confirm applies the reviewed request: `create-scale-set` adds only a draft scale set and no project (docs/API.md:
    "adding a scale set remains explicitly scoped and does not add projects"); `add-project` always creates a new
    logical project UUID and readable key; `add-project-placements` appends only new environments. A project has one
    placement per environment, and a project number is unique per physical scale set. A runtime `deploy` of a
    project needs the project's explicit placement in the selected scale set (catalog_runtime.py). A stale
    `expected_revision` is refused like the real API does.

    Single-writer coordination (the default): a runtime deploy is refused unless the live enrollment covers its
    resource group. The bootstrap enrolled scale set 001 and its project001; `enroll-scale-set` covers an added scale
    set's common group plus the group of every project placed on it when it is prepared, never a later one.
    """

    def __init__(self, coordination: str = "single-writer", enroll_routes: bool = True, enroll_blockers=()):
        self.document = copy.deepcopy(CATALOG)
        self.pending: dict[str, dict] = {}
        self.jobs = 0
        self.coordination = coordination
        self.enroll_routes = enroll_routes  # False: an older API without the operation (404 on its routes)
        self.enroll_blockers = list(enroll_blockers)
        self.enrolled = {"aif-121-esml-common-sdc-dev-001", "aif-121-esml-project001-sdc-dev-001-rg"}
        self.enrollments: dict[str, dict] = {}

    def _groups(self, scale: dict, project: dict | None) -> str:
        f = self.factory
        base = f"{f['prefix']}esml-" + (f"project{project['number']}-" if project else "common-")
        name = f"{base}{f['region_short_name']}-{scale['environment']}-{scale['suffix']}"
        return name + "-rg" if project else name

    def _require_enrolled(self, body: dict) -> None:
        if self.coordination != "single-writer":
            return
        scale = self._scale(body["scale_set_id"])
        project = next((p for p in self.factory["projects"] if p["id"] == body.get("project_id")), None)
        group = self._groups(scale, project)
        if group not in self.enrolled:
            raise Refused(f"The single-writer binding and live enrollment do not cover {group}; enroll the scale set "
                          "first.")

    def enroll_prepare(self, body: dict) -> dict:
        if set(body) != {"contract_version", "folder", "factory_id", "scale_set_id"}:
            raise Refused("closed request")
        scale = self._scale(body["scale_set_id"])
        placed = [p for p in self.factory["projects"]
                  if any(pl["scale_set_id"] == scale["id"] for pl in p["placements"])]
        groups = [self._groups(scale, None)] + [self._groups(scale, p) for p in placed]
        phrase = f"ENROLL SCALE SET {self.factory['prefix'].rstrip('-')} {scale['suffix']}"
        blockers = [BLOB_BLOCKER] if self.coordination != "single-writer" else self.enroll_blockers
        confirmation_id = str(uuid.uuid4())
        preview = enroll_preview(body, groups, phrase=phrase, blockers=blockers, confirmation_id=confirmation_id)
        if not blockers:
            self.enrollments[confirmation_id] = {"preview": preview, "groups": groups}
        return preview

    def enroll_confirm(self, body: dict) -> dict:
        review = self.enrollments.pop(body["confirmation_id"], None)
        if review is None:
            raise Refused("Scale-set enrollment blocked: the review is unknown or was already used.")
        preview = review["preview"]
        if (body["preview_hash"], body["confirmation_phrase"]) != (preview["preview_hash"],
                                                                   preview["confirmation_phrase"]):
            raise Refused("Scale-set enrollment blocked: the confirmation does not match the review.")
        self.enrolled.update(review["groups"])
        return enroll_result(preview)

    @property
    def factory(self) -> dict:
        return self.document["factories"][0]

    def _bump(self) -> None:
        text = json.dumps(self.document["factories"], sort_keys=True)
        self.document["revision"] = hashlib.sha256(text.encode()).hexdigest()

    def _scale(self, scale_set_id: str) -> dict:
        found = next((s for s in self.factory["scale_sets"] if s["id"] == scale_set_id), None)
        if found is None:
            raise Refused("Select an exact scale set belonging to this factory.")
        return found

    def _check_placements(self, project: dict, placements: list[dict]) -> None:
        environments = {p["environment"] for p in project["placements"]}
        for placement in placements:
            scale = self._scale(placement["scale_set_id"])
            if scale["environment"] != placement["environment"] or placement["environment"] in environments:
                raise Refused("Project placements require one matching scale set per environment.")
            environments.add(placement["environment"])
            if any(other["number"] == project["number"] and other.get("id") != project.get("id")
                   and any(p["scale_set_id"] == scale["id"] for p in other["placements"])
                   for other in self.factory["projects"]):
                raise Refused("Project number conflicts in the selected physical scope.")

    def prepare(self, body: dict) -> dict:
        if body.get("expected_revision") not in (None, self.document["revision"]):
            raise Refused("The catalog revision changed; refresh and prepare again.")
        action = body["action"]
        if action == "deploy":
            self._scale(body["scale_set_id"])
            if body.get("project_id") and not any(
                    project["id"] == body["project_id"]
                    and any(p["scale_set_id"] == body["scale_set_id"] for p in project["placements"])
                    for project in self.factory["projects"]):
                raise Refused("Project must have an explicit placement in the selected scale set.")
            self._require_enrolled(body)
        elif action == "add-project":
            self._check_placements({"number": body["project"]["number"], "placements": []},
                                   body["project"]["placements"])
        elif action == "add-project-placements":
            project = next(p for p in self.factory["projects"] if p["id"] == body["project_id"])
            self._check_placements(project, body["placements"])
        confirmation_id = str(uuid.uuid4())
        self.pending[confirmation_id] = copy.deepcopy(body)
        # A future expiry: the SDK refuses a review that has expired by the real clock before it saves a receipt.
        return {**PREVIEW, "confirmation_id": confirmation_id, "can_execute": True, "blockers": [],
                "source_revision": self.document["revision"], "expires_at": "2099-01-01T00:00:00Z",
                "operation_mode": "runtime" if action == "deploy" else "configuration"}

    def confirm(self, confirmation_id: str) -> dict:
        body = self.pending.pop(confirmation_id, None)
        if body is None:
            raise Refused("Unknown or already used confirmation.")
        action, job = body["action"], None
        if action == "create-scale-set":
            for item in body["scale_sets"]:
                self.factory["scale_sets"].append({"id": str(uuid.uuid4()), "environment": item["environment"],
                                                   "suffix": item["suffix"], "status": "draft"})
        elif action == "add-project":
            number = body["project"]["number"]
            keys = {p["key"] for p in self.factory["projects"]}
            key, counter = f"project-{number}", 1
            while key in keys:
                counter += 1
                key = f"project-{number}-{counter}"
            self.factory["projects"].append({"id": str(uuid.uuid4()), "key": key, "number": number,
                                             "display_name": body["project"]["display_name"], "status": "draft",
                                             "placements": copy.deepcopy(body["project"]["placements"])})
        elif action == "add-project-placements":
            project = next(p for p in self.factory["projects"] if p["id"] == body["project_id"])
            project["placements"].extend(copy.deepcopy(body["placements"]))
        else:
            self.jobs += 1
            job = {**JOB, "id": str(uuid.UUID(int=self.jobs)), "action": action}
        if job is None:
            self._bump()
        return {"contract_version": 1, "catalog": copy.deepcopy(self.document), "job": job}

    def respond(self, method: str, path: str, body):
        if method == "GET" and path == "/api/v1/factory-catalog":
            return copy.deepcopy(self.document)
        if method == "GET" and path.startswith("/api/v1/factory-catalog/jobs/"):
            return {**JOB, "id": path.rsplit("/", 1)[1], "status": "succeeded"}
        if path == "/api/v1/factory-catalog/prepare":
            return self.prepare(body)
        if path == "/api/v1/factory-catalog/confirm":
            return self.confirm(body["confirmation_id"])
        if path in (ENROLL_PREPARE, ENROLL_CONFIRM):
            if not self.enroll_routes:
                return None  # an older API: 404 {"detail": "not found"}
            return self.enroll_prepare(body) if path == ENROLL_PREPARE else self.enroll_confirm(body)
        return _response(method, path, body)


class FakeFactoryApi:
    def __init__(self, api_key: str = "test-key", *, missing_catalog: bool = False,
                 slow: dict[str, float] | None = None, stateful: bool = False, **state_options):
        self.api_key = api_key
        self.missing_catalog = missing_catalog  # a new consumer folder: the API answers its catalog with 404
        self.slow = slow or {}  # path -> seconds before answering, like a real runtime review
        # pink's catalog semantics instead of fixed answers (coordination, enroll_routes, enroll_blockers)
        self.state = StatefulCatalog(**state_options) if stateful else None
        self.calls: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _handle(self):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                outer.calls.append({"method": self.command, "path": parts.path,
                                    "query": sorted(parse_qsl(parts.query, keep_blank_values=True)),
                                    "body": json.loads(raw) if raw else None,
                                    "key": self.headers.get("X-API-Key") == outer.api_key})
                status = 200
                try:
                    respond = outer.state.respond if outer.state else _response
                    payload = respond(self.command, parts.path, json.loads(raw) if raw else None)
                except Refused as refusal:
                    payload, status = {"detail": str(refusal)}, 409
                if outer.missing_catalog and parts.path == "/api/v1/factory-catalog":
                    payload = None
                status = status if payload is not None else 404
                data = json.dumps(payload if payload is not None else {"detail": "not found"}).encode()
                time.sleep(outer.slow.get(parts.path, 0))
                try:
                    self.send_response(status)
                except OSError:  # the caller timed out and closed the connection
                    return
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
