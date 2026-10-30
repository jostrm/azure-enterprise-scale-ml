"""Scenario 3 (add or update a project) in two reviewed steps, with the reference Function's HTTP contract.

prepare -> review (awaiting_confirmation) -> confirm (sent once, never retried) -> next review ... -> succeeded.
Nothing here imports Azure Functions, so tests call it directly. Operations live in memory: use one instance
locally, and a durable store (Azure Table storage) before more than one instance runs.
"""

import hmac
import re
import threading
import uuid
from datetime import datetime, timezone

SCENARIO = "add-or-update-project"
STEPS = ("configure", "deploy-project")
ENVIRONMENTS = {"dev": "dev", "test": "stage", "prod": "prod"}  # Azure names -> catalog names
PROJECT_ID = re.compile(r"(?P<prefix>[a-z0-9-]+-)esml-project(?P<number>\d{3})-(?P<region>[a-z0-9]+)"
                        r"-(?P<env>dev|test|prod)-(?P<suffix>\d{3})-rg")
SETTLED = {"awaiting_confirmation", "succeeded", "failed", "blocked", "expired"}


class Problem(Exception):
    """An RFC 9457 problem: HTTP status, a stable code and a detail without secrets."""

    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Lifecycle:
    def __init__(self, client, folder):
        self._client, self._folder = client, folder
        self._operations, self._lock = {}, threading.Lock()

    # ----- queries -----

    def health(self):
        return {"status": "ok", "backend": getattr(self._client, "name", "sdk"), "executor": "inprocess"}

    def list(self):
        rows = sorted(self._operations.values(), key=lambda op: (op["createdAt"], op["operationId"]), reverse=True)
        keys = ("operationId", "scenario", "target", "status", "currentStep", "createdAt", "updatedAt")
        return {"operations": [{key: op[key] for key in keys} for op in rows]}

    def get(self, operation_id):
        operation = self._load(operation_id)
        step = operation["steps"][operation["currentStep"]]
        if step["status"] == "running":
            self._poll(operation, step)
        return self._public(operation)

    # ----- commands -----

    def prepare(self, scenario, body):
        if scenario != SCENARIO:
            raise Problem(400, "unsupported-scenario", f"This Function runs {SCENARIO} only.")
        target = str((body or {}).get("projectId") or "")
        match = PROJECT_ID.fullmatch(target)
        if not match:
            raise Problem(400, "invalid-id", "projectId must be a project resource group name.")
        settings = (body or {}).get("settings") or {}
        if not isinstance(settings, dict):
            raise Problem(400, "validation-failed", "settings must be a JSON object.")
        operation = {"operationId": str(uuid.uuid4()), "scenario": SCENARIO, "target": target, "status": "preparing",
                     "currentStep": 0, "createdAt": _now(), "updatedAt": _now(), "settings": settings,
                     "resolved": self._resolve(match),
                     "steps": [{"index": i, "name": name, "status": "pending", "preview": None, "failure": None}
                               for i, name in enumerate(STEPS)]}
        with self._lock:
            self._operations[operation["operationId"]] = operation
        self._review(operation)
        return self._public(operation)

    def confirm(self, operation_id, body):
        operation = self._load(operation_id)
        with self._lock:  # one confirm at a time: it is saved as confirming before the call goes out
            step = operation["steps"][operation["currentStep"]]
            if step["status"] != "awaiting_confirmation":
                raise Problem(409, "invalid-state", f"Step '{step['name']}' is {step['status']}.")
            if datetime.fromisoformat(step["preview"]["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                self._set(operation, step, "expired")
                raise Problem(410, "confirmation-expired", "The review expired; prepare the operation again.")
            token = str((body or {}).get("confirmationToken") or "")
            if not hmac.compare_digest(token, step["preview"]["confirmationToken"]):
                raise Problem(400, "confirmation-mismatch", "The confirmation token does not match the current review.")
            self._set(operation, step, "confirming")
        try:
            confirmed = self._call(lambda: self._client.catalog_confirm(self._folder, step["confirmation_id"]))
        except Problem as problem:  # never retried: the outcome of a failed confirm is unknown
            step["failure"] = {"code": "completion-unknown", "detail": problem.detail}
            self._set(operation, step, "failed")
            return self._public(operation)
        if step["name"] == "configure":
            self._resolve_project(operation, confirmed.get("catalog") or self._catalog())
            self._set(operation, step, "succeeded")
            self._advance(operation)
        else:
            step["job_id"] = confirmed["job"]["id"]
            self._set(operation, step, "running")
        return self._public(operation)

    # ----- steps -----

    def _review(self, operation):
        step = operation["steps"][operation["currentStep"]]
        r, revision = operation["resolved"], self._catalog().get("revision")
        self._set(operation, step, "preparing")
        try:
            if step["name"] == "configure" and r["project_id"] is None:
                review = self._call(lambda: self._client.project_add_prepare(
                    self._folder, r["factory_id"], number=r["number"], display_name=f"Project {r['number']}",
                    placements=[{"environment": r["environment"], "scale_set_id": r["scale_set_id"]}],
                    settings=operation["settings"] or None, expected_revision=revision))
            elif step["name"] == "configure":
                review = self._call(lambda: self._client.catalog_settings_prepare(
                    self._folder, r["factory_id"], operation["settings"], scale_set_id=r["scale_set_id"],
                    project_id=r["project_id"], expected_revision=revision))
            else:
                review = self._call(lambda: self._client.catalog_prepare({
                    "folder": self._folder, "contract_version": 1, "action": "deploy", "expected_revision": revision,
                    "factory_id": r["factory_id"], "scale_set_id": r["scale_set_id"], "project_id": r["project_id"]}))
        except Problem as problem:
            step["failure"] = {"code": problem.code, "detail": problem.detail}
            self._set(operation, step, "failed")
            return
        configure = step["name"] == "configure"
        step["confirmation_id"] = review["confirmation_id"]
        step["preview"] = {
            "plan": [review.get("summary") or ""] + [str(e) for e in review.get("effects") or []]
                    + ([f"Action: {review.get('action')}"] if configure and review.get("action") else []),
            "affectedResourceGroups": [] if configure else [operation["target"]],
            "blockers": [str(b) for b in review.get("blockers") or []],
            "warnings": [str(w) for w in review.get("warnings") or []],
            "canExecute": review.get("can_execute") is True, "expiresAt": review["expires_at"],
            "confirmationPhrase": None, "confirmationToken": uuid.uuid4().hex}
        self._set(operation, step, "awaiting_confirmation" if step["preview"]["canExecute"] else "blocked")

    def _poll(self, operation, step):
        job = self._call(lambda: self._client.catalog_job(self._folder, step["job_id"]))
        if job.get("status") == "succeeded":
            self._set(operation, step, "succeeded")
            self._advance(operation)
        elif job.get("status") in ("failed", "interrupted"):
            step["failure"] = {"code": "run-failed", "detail": str(job.get("message") or "The deployment failed.")}
            self._set(operation, step, "failed")

    def _advance(self, operation):
        if operation["currentStep"] + 1 < len(operation["steps"]):
            operation["currentStep"] += 1
            self._review(operation)
        else:
            operation["status"], operation["updatedAt"] = "succeeded", _now()

    # ----- helpers -----

    def _resolve(self, match):
        catalog = self._catalog()
        factory = next((f for f in catalog.get("factories") or [] if f.get("prefix") == match["prefix"]
                        and f.get("region_short_name") == match["region"]), None)
        if factory is None:
            raise Problem(404, "unknown-id", "No factory in the catalog matches this projectId.")
        environment = ENVIRONMENTS[match["env"]]
        scale_set = next((s for s in factory["scale_sets"] if s["environment"] == environment
                          and str(s["suffix"]) == match["suffix"]), None)
        if scale_set is None:
            raise Problem(404, "unknown-id", "No scale set in the catalog matches this projectId.")
        resolved = {"factory_id": factory["id"], "scale_set_id": scale_set["id"], "environment": environment,
                    "number": match["number"], "project_id": None}
        self._find_project(resolved, factory)
        return resolved

    def _resolve_project(self, operation, catalog):
        factory = next(f for f in catalog["factories"] if f["id"] == operation["resolved"]["factory_id"])
        self._find_project(operation["resolved"], factory)

    @staticmethod
    def _find_project(resolved, factory):
        for project in factory.get("projects") or []:
            if str(project["number"]) == resolved["number"] and any(
                    p.get("scale_set_id") == resolved["scale_set_id"] for p in project.get("placements") or []):
                resolved["project_id"] = project["id"]

    def _catalog(self):
        return self._call(lambda: self._client.catalog_list(self._folder))

    @staticmethod
    def _call(call):
        """Factory API errors (SDK or mock) become problems; their text never includes the key."""
        try:
            return call()
        except Problem:
            raise
        except Exception as error:  # noqa: BLE001 - azurefactory.errors.* and MockApiError share message/status
            status = getattr(error, "status", None)
            code = "upstream-refused" if status in (401, 403, 409) else "upstream-error"
            raise Problem(502, code, str(getattr(error, "message", error))[:300]) from None

    def _load(self, operation_id):
        operation = self._operations.get(operation_id)
        if operation is None:
            raise Problem(404, "operation-not-found", "No such operation.")
        return operation

    @staticmethod
    def _set(operation, step, status):
        step["status"], operation["status"], operation["updatedAt"] = status, status, _now()

    @staticmethod
    def _public(operation):
        steps = []
        for step in operation["steps"]:
            preview = dict(step["preview"]) if step["preview"] else None
            if preview and step["status"] != "awaiting_confirmation":
                preview["confirmationToken"] = None  # a token only while the step waits for you
            steps.append({"index": step["index"], "name": step["name"], "status": step["status"],
                          "preview": preview, "failure": step["failure"]})
        public = {key: operation[key] for key in ("operationId", "scenario", "target", "status", "currentStep",
                                                  "createdAt", "updatedAt")}
        return {**public, "steps": steps}
