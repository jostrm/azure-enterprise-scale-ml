"""Mock Factory API: a persistent catalog in the state store, previews and confirmations like the real API.

It keeps state between invocations (add -> 409 -> delete -> 404) and supports simulated outcomes through the
prepare body's `simulate` object: `failAt` (step or resource group), `uncertainAt` and `rejectAt` (step) and
`dropEventAt` (no relay for that run, so the poller has to recover it).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable

from ..application import resolver
from ..domain.errors import Conflict, RevisionMismatch, UnknownId, UpstreamTimeout
from ..domain.ids import FactoryId, ProjectId, ScalesetId
from ..domain.operation import Preview, StepKind
from ..domain.scenarios import Scenario
from ..ports import Catalog, ConfirmResult, StateStore, StepRequest, StoreConflict

PARTITION, KEY = "mockcatalog", "catalog"


class MockFactoryBackend:
    name = "mock"

    def __init__(self, store: StateStore, *, clock, review_ttl_seconds: int = 600,
                 ids: Callable[[], str] | None = None):
        self._store = store
        self._clock = clock
        self._ttl = review_ttl_seconds
        self._ids = ids or (lambda: str(uuid.uuid4()))

    # ----- catalog state -----

    def _load(self) -> tuple[dict[str, Any], str | None]:
        found = self._store.get(PARTITION, KEY)
        return (found[0], found[1]) if found else ({"factories": []}, None)

    def _save(self, data: dict[str, Any], etag: str | None) -> None:
        try:
            if etag is None:
                self._store.insert(PARTITION, KEY, data)
            else:
                self._store.replace(PARTITION, KEY, data, etag)
        except StoreConflict:
            raise Conflict("The mock catalog changed at the same time; prepare again.") from None

    @staticmethod
    def _revision(data: dict[str, Any]) -> str:
        text = json.dumps(data.get("factories", []), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def catalog(self) -> Catalog:
        data, _ = self._load()
        return Catalog.from_api({"revision": self._revision(data), "factories": data["factories"]})

    # ----- prepare / confirm -----

    def prepare(self, request: StepRequest) -> Preview:
        data, _ = self._load()
        action = self._action(request)
        groups = [] if request.kind is StepKind.CONFIGURE else self._groups(request, data)
        plan = self._plan(request, action, groups)
        phrase = None
        if request.step_name == "delete-factory":
            phrase = f"DELETE {request.resolved['factory_key']}"
        ttl = int(request.options.get("ttlSeconds") or self._ttl)
        return Preview(plan=plan, affected_resource_groups=groups, blockers=[], can_execute=True,
                       expires_at=self._clock.now().timestamp() + ttl, confirmation_phrase=phrase,
                       backend_ref={"confirmation_id": self._ids(), "action": action,
                                    "expected_revision": self._revision(data)})

    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult:
        simulate = request.options.get("simulate") or {}
        if simulate.get("uncertainAt") == request.step_name:
            raise UpstreamTimeout("Simulated: the Factory API did not answer the confirmation in time.")
        if simulate.get("rejectAt") == request.step_name:
            raise RevisionMismatch("Simulated: the catalog changed since this review.")
        data, etag = self._load()
        if self._revision(data) != preview.backend_ref.get("expected_revision"):
            raise RevisionMismatch("The catalog changed since this review; prepare the operation again.")
        if request.kind is StepKind.CONFIGURE:
            updates = self._apply_configuration(request, data)
            self._save(data, etag)
            return ConfirmResult(job={"kind": "catalog", "confirmation_id": preview.backend_ref["confirmation_id"]},
                                 targets=[], resolved_updates=updates)
        return ConfirmResult(job={"job_id": self._ids(), "action": preview.backend_ref["action"]},
                             targets=list(preview.affected_resource_groups))

    def finalize(self, request: StepRequest, succeeded: bool) -> None:
        """Deletions leave the catalog only after verified success, like the real API."""
        if not succeeded or request.kind is not StepKind.DELETE:
            return
        data, etag = self._load()
        factories = data["factories"]
        factory = self._factory(data, request.resolved["factory_id"])
        if request.step_name == "delete-factory":
            factories.remove(factory)
        elif request.step_name == "delete-scaleset":
            scaleset_id = request.resolved["scale_set_id"]
            factory["scale_sets"] = [s for s in factory["scale_sets"] if s["id"] != scaleset_id]
            for project in factory["projects"]:
                project["placements"] = [p for p in project["placements"] if p["scale_set_id"] != scaleset_id]
            factory["projects"] = [p for p in factory["projects"] if p["placements"]]
        elif request.step_name == "delete-project":
            for project in factory["projects"]:
                if project["id"] == request.resolved["project_id"]:
                    project["placements"] = [p for p in project["placements"]
                                             if p["scale_set_id"] != request.resolved["scale_set_id"]]
            factory["projects"] = [p for p in factory["projects"] if p["placements"]]
        self._save(data, etag)

    # ----- helpers -----

    def _action(self, request: StepRequest) -> str:
        if request.kind is StepKind.CONFIGURE:
            return {Scenario.INIT_FACTORY: "create-factory", Scenario.ADD_SCALESET: "create-scale-set"}.get(
                request.scenario, "add-project" if request.resolved.get("mode") == "add" else "configure-settings")
        return request.step_name if request.kind is StepKind.DELETE else "deploy"

    def _plan(self, request: StepRequest, action: str, groups: list[str]) -> list[str]:
        if request.kind is StepKind.CONFIGURE:
            return [f"Save the catalog change '{action}' for {request.target} (configuration only, no Azure change)."]
        verb = "Delete" if request.kind is StepKind.DELETE else "Deploy"
        return [f"{verb} resource group {group}" for group in groups]

    def _groups(self, request: StepRequest, data: dict[str, Any]) -> list[str]:
        name, target = request.step_name, request.target
        if request.scenario is Scenario.INIT_FACTORY:
            factory = FactoryId.parse(target)
            scaleset = ScalesetId(factory, "001")
            stages = {"deploy-connectivity": [f"{factory.prefix}-connectivity-{factory.region_code}-{factory.env}"],
                      "deploy-common": [scaleset.common_resource_group],
                      "deploy-project001": [str(ProjectId(scaleset, "001"))]}
            if name == "bootstrap":
                return [group for stage in stages.values() for group in stage]
            return stages[name]
        if request.scenario is Scenario.ADD_SCALESET:
            scaleset = ScalesetId.parse(target)
            return [scaleset.common_resource_group] if name == "deploy-common" else [str(ProjectId(scaleset, "001"))]
        if request.scenario in (Scenario.ADD_OR_UPDATE_PROJECT, Scenario.DELETE_PROJECT):
            return [target]
        catalog = Catalog.from_api({"revision": "", "factories": data["factories"]})
        factory = next((f for f in catalog.factories if f.id == request.resolved["factory_id"]), None)
        if factory is None:
            raise UnknownId(f"{target} is no longer in the catalog.")
        scale_sets = [s for s in factory.scale_sets
                      if request.step_name == "delete-factory" or s.id == request.resolved["scale_set_id"]]
        groups = []
        for scaleset in sorted(scale_sets, key=lambda s: s.suffix):
            identity = resolver.scaleset_id(factory, scaleset)
            groups += [str(ProjectId(identity, p.number)) for p in resolver.projects_in(factory, scaleset)]
            groups.append(identity.common_resource_group)
        return groups

    def _factory(self, data: dict[str, Any], factory_id: str) -> dict[str, Any]:
        for factory in data["factories"]:
            if factory["id"] == factory_id:
                return factory
        raise UnknownId("The factory is no longer in the catalog.")

    def _apply_configuration(self, request: StepRequest, data: dict[str, Any]) -> dict[str, Any]:
        resolved, settings = request.resolved, request.settings
        if request.scenario is Scenario.INIT_FACTORY:
            factory_id, scaleset_id, project_id = self._ids(), self._ids(), self._ids()
            key = f"{resolved['prefix']}{resolved['region']}"
            data["factories"].append({
                "id": factory_id, "key": key, "kind": "ai", "prefix": resolved["prefix"], "region": resolved["region"],
                "region_short_name": resolved["region_code"], "status": "configured",
                "scale_sets": [{"id": scaleset_id, "environment": resolved["environment"], "suffix": "001",
                                "status": "configured"}],
                "projects": [{"id": project_id, "key": "project-001-001", "number": "001",
                              "display_name": "Project 001", "settings": dict(settings),
                              "placements": [{"environment": resolved["environment"], "scale_set_id": scaleset_id}]}],
            })
            return {"factory_id": factory_id, "factory_key": key, "scale_set_id": scaleset_id, "project_id": project_id}
        factory = self._factory(data, resolved["factory_id"])
        if request.scenario is Scenario.ADD_SCALESET:
            scaleset_id = self._ids()
            factory["scale_sets"].append({"id": scaleset_id, "environment": resolved["environment"],
                                          "suffix": resolved["suffix"], "status": "configured"})
            project_id = self._place(factory, "001", resolved["environment"], scaleset_id, {})
            return {"scale_set_id": scaleset_id, "project_id": project_id}
        if resolved.get("mode") == "add":
            project_id = self._place(factory, resolved["project_number"], resolved["environment"],
                                     resolved["scale_set_id"], settings)
            return {"project_id": project_id}
        for project in factory["projects"]:
            if project["id"] == resolved["project_id"]:
                project.setdefault("settings", {}).update(settings)
        return {}

    def _place(self, factory: dict[str, Any], number: str, environment: str, scaleset_id: str,
               settings: dict[str, Any]) -> str:
        for project in factory["projects"]:
            if project["number"] == number:
                project["placements"].append({"environment": environment, "scale_set_id": scaleset_id})
                project.setdefault("settings", {}).update(settings)
                return project["id"]
        project_id = self._ids()
        factory["projects"].append({"id": project_id, "key": f"project-{number}-001", "number": number,
                                    "display_name": f"Project {number}", "settings": dict(settings),
                                    "placements": [{"environment": environment, "scale_set_id": scaleset_id}]})
        return project_id
