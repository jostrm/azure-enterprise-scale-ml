"""Shared Factory API backend (Template Method): maps steps to Factory API calls; subclasses do the transport.

REST (option 1) and SDK (option 2) inherit this class, so a scenario makes the same API calls whichever transport is
configured; `tests/test_adapter_parity.py` proves it against a fake API. Routes and bodies follow
environment_setup/azurefactory-cli (client.py, catalog_requests.py) and pink's docs/API.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ..domain.errors import UpstreamError, ValidationFailed
from ..domain.operation import Preview, StepKind
from ..domain.scenarios import Scenario
from ..ports import Catalog, ConfirmResult, StepRequest

RUNTIME_STEPS = {"deploy-common", "deploy-project001", "deploy-project", "delete-project", "delete-scaleset"}


def deploy_request(folder: str, factory_id: str, scale_set_id: str, project_id: str | None,
                   expected_revision: str | None) -> dict[str, Any]:
    """Runtime deploy body, as `azurefactory runtime deploy` sends it (None values dropped)."""
    body = {"folder": folder, "contract_version": 1, "action": "deploy", "expected_revision": expected_revision,
            "factory_id": factory_id, "scale_set_id": scale_set_id, "project_id": project_id}
    return {key: value for key, value in body.items() if value is not None}


def scale_set_body(request: StepRequest, suffix: str) -> dict[str, Any]:
    spec = request.options.get("scaleSet")
    if not isinstance(spec, dict):
        raise ValidationFailed("Send scaleSet {subscriptionId, tenantId, orchestrator, vnetCidr} for the Factory API.")
    network = {"vnet_cidr": spec["vnetCidr"], "max_projects": int(spec.get("maxProjects", 7))}
    if spec.get("commonSubnets"):
        network["common_subnets"] = dict(spec["commonSubnets"])
    return {"environment": request.resolved["environment"], "suffix": suffix, "subscription_id": spec["subscriptionId"],
            "tenant_id": spec["tenantId"], "orchestrator": spec["orchestrator"], "network": network}


def preview_from_api(response: dict[str, Any]) -> Preview:
    groups = sorted({target["resource_group"] for target in response.get("deletion_targets") or []
                     if isinstance(target, dict) and target.get("resource_group")})
    warnings = [str(item) for item in response.get("warnings") or []]
    warnings += [str(item.get("message")) for item in response.get("network_warnings") or [] if isinstance(item, dict)]
    warnings += [str(item) for item in response.get("address_warnings") or []]
    plan = [str(response["summary"])] if response.get("summary") else []
    plan += [str(effect) for effect in response.get("effects") or []]
    expires = response.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expires).replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise UpstreamError("The Factory API review has no valid expires_at.") from None
    reference = {key: response.get(key) for key in ("confirmation_id", "preview_hash", "source_revision", "action",
                                                     "operation_mode", "workflow_id", "authorization_hash")
                 if response.get(key) is not None}
    return Preview(plan=plan, affected_resource_groups=groups, blockers=[str(item) for item in response.get("blockers") or []],
                   can_execute=response.get("can_execute") is True, expires_at=expires_at,
                   confirmation_phrase=response.get("confirmation_phrase"), backend_ref=reference, warnings=warnings)


class FactoryApiBackend(ABC):
    """Steps -> Factory API calls. Subclasses implement the primitive calls (REST or SDK)."""

    name = "api"

    def __init__(self, folder: str):
        if not folder:
            raise ValidationFailed("AIF_FACTORY_FOLDER (the consumer repo's azurefactory folder on the API host) is required.")
        self.folder = folder

    # ----- FactoryBackend port -----

    def catalog(self) -> Catalog:
        return Catalog.from_api(self._catalog_list())

    def prepare(self, request: StepRequest) -> Preview:
        revision = self._catalog_list().get("revision")
        return preview_from_api(self._prepare_call(request, revision))

    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult:
        ref = preview.backend_ref
        name = request.step_name
        if request.kind is StepKind.CONFIGURE:
            confirmed = self._catalog_confirm(ref["confirmation_id"])
            summary = confirmed.get("catalog") or self._catalog_list()
            return ConfirmResult(job={"kind": "catalog"}, targets=[],
                                 resolved_updates=_created_ids(request, Catalog.from_api(summary)))
        if name == "delete-factory":
            job = _job(self._delete_factory_confirm(ref["confirmation_id"], ref.get("preview_hash"), phrase))
        elif request.kind is StepKind.BOOTSTRAP:
            workflow = self._workflow_start(ref["workflow_id"], ref["confirmation_id"], ref.get("authorization_hash"))
            identifier = str(workflow.get("workflow_id") or ref["workflow_id"])
            return ConfirmResult(job={"kind": "workflow", "workflow_id": identifier}, targets=[f"api-workflow-{identifier}"])
        elif name in RUNTIME_STEPS:
            job = _job(self._catalog_confirm(ref["confirmation_id"]))
        else:
            raise ValidationFailed(f"Step '{name}' has no Factory API confirmation.")
        return ConfirmResult(job={"kind": "job", "job_id": job["id"], "status": job.get("status")},
                             targets=[f"api-job-{job['id']}"])

    def finalize(self, request: StepRequest, succeeded: bool) -> None:
        """The Factory API owns the catalog; nothing to do here."""

    def job_status(self, job: dict[str, Any]) -> dict[str, Any]:
        if job.get("kind") == "workflow":
            return self._workflow_status(job["workflow_id"])
        return self._job(job["job_id"])

    # ----- step -> call mapping -----

    def _prepare_call(self, request: StepRequest, revision: str | None) -> dict[str, Any]:
        r, name = request.resolved, request.step_name
        if request.kind is StepKind.CONFIGURE:
            if request.scenario is Scenario.INIT_FACTORY:
                return self._create_factory(prefix=r["prefix"], region=r["region"], region_short_name=r["region_code"],
                                            scale_sets=[scale_set_body(request, "001")],
                                            settings=request.settings or None, expected_revision=revision)
            if request.scenario is Scenario.ADD_SCALESET:
                return self._add_scaleset(r["factory_id"], [scale_set_body(request, r["suffix"])], revision)
            if r.get("mode") == "add":
                return self._add_project(r["factory_id"], r["project_number"], f"Project {r['project_number']}",
                                         [{"environment": r["environment"], "scale_set_id": r["scale_set_id"]}],
                                         request.settings or None, revision)
            return self._configure_settings(r["factory_id"], request.settings, r["scale_set_id"], r["project_id"], revision)
        if request.kind is StepKind.BOOTSTRAP:
            return self._workflow_prepare(self._workflow_request(request, revision))
        if name == "deploy-common":
            return self._deploy(deploy_request(self.folder, r["factory_id"], r["scale_set_id"], None, revision))
        if name in ("deploy-project001", "deploy-project"):
            return self._deploy(deploy_request(self.folder, r["factory_id"], r["scale_set_id"], r["project_id"], revision))
        if name == "delete-project":
            return self._delete_project(r["factory_id"], r["project_id"], [r["environment"]], r["include_project_subnets"],
                                        r["include_keyvault_and_resource_group"], revision, r["scale_set_id"])
        if name == "delete-scaleset":
            return self._delete_scaleset(r["factory_id"], r["scale_set_id"], revision)
        if name == "delete-factory":
            return self._delete_factory_prepare({"contract_version": 1, "folder": self.folder,
                                                 "factory_id": r["factory_id"], "expected_revision": revision})
        raise ValidationFailed(f"Step '{name}' has no Factory API preparation.")

    def _workflow_request(self, request: StepRequest, revision: str | None) -> dict[str, Any]:
        config = request.options.get("bootstrapConfig")
        if not isinstance(config, dict):
            raise ValidationFailed("Send bootstrapConfig (the API's Full bootstrap configuration) for init-factory.")
        r = request.resolved
        scope = {"folder": self.folder, "factory_id": r["factory_id"], "scale_set_id": r["scale_set_id"]}
        if r.get("project_id"):
            scope["project_id"] = r["project_id"]
        return {"contract_version": 1, "operation": "create-factory", "execution_mode": "privileged-bootstrap",
                "creation_mode": "full-bootstrap", "scope": scope, "expected_revision": revision,
                "bootstrap_config": config}

    # ----- primitives (transport) -----

    @abstractmethod
    def _catalog_list(self) -> dict[str, Any]: ...

    @abstractmethod
    def _create_factory(self, *, prefix, region, region_short_name, scale_sets, settings, expected_revision): ...

    @abstractmethod
    def _add_scaleset(self, factory_id, scale_sets, expected_revision): ...

    @abstractmethod
    def _add_project(self, factory_id, number, display_name, placements, settings, expected_revision): ...

    @abstractmethod
    def _configure_settings(self, factory_id, settings, scale_set_id, project_id, expected_revision): ...

    @abstractmethod
    def _deploy(self, body): ...

    @abstractmethod
    def _delete_project(self, factory_id, project_id, environments, include_project_subnets,
                        include_keyvault_and_resource_group, expected_revision, scale_set_id): ...

    @abstractmethod
    def _delete_scaleset(self, factory_id, scale_set_id, expected_revision): ...

    @abstractmethod
    def _delete_factory_prepare(self, body): ...

    @abstractmethod
    def _catalog_confirm(self, confirmation_id): ...

    @abstractmethod
    def _delete_factory_confirm(self, confirmation_id, preview_hash, phrase): ...

    @abstractmethod
    def _workflow_prepare(self, body): ...

    @abstractmethod
    def _workflow_start(self, workflow_id, confirmation_id, authorization_hash): ...

    @abstractmethod
    def _workflow_status(self, workflow_id): ...

    @abstractmethod
    def _job(self, job_id): ...


def _job(confirmed: dict[str, Any]) -> dict[str, Any]:
    job = confirmed.get("job") if isinstance(confirmed, dict) else None
    if not isinstance(job, dict) or not job.get("id"):
        raise UpstreamError("The Factory API confirmed without returning a job; check the API's job list before acting.")
    return job


def _created_ids(request: StepRequest, catalog: Catalog) -> dict[str, Any]:
    """Find the catalog UUIDs a configuration confirm created, by the same natural keys the step used."""
    r = request.resolved
    if request.scenario is Scenario.INIT_FACTORY:
        factory = next((f for f in catalog.factories if f.prefix == r["prefix"] and f.region == r["region"]), None)
    else:
        factory = next((f for f in catalog.factories if f.id == r.get("factory_id")), None)
    if factory is None:
        return {}
    updates: dict[str, Any] = {"factory_id": factory.id, "factory_key": factory.key}
    suffix = r.get("suffix", "001")
    scaleset = next((s for s in factory.scale_sets
                     if s.environment == r["environment"] and s.suffix == suffix), None) if "scale_set_id" not in r \
        else next((s for s in factory.scale_sets if s.id == r["scale_set_id"]), None)
    if scaleset is None:
        return updates
    updates["scale_set_id"] = scaleset.id
    number = r.get("project_number", "001")
    project = next((p for p in factory.projects if p.number == number
                    and any(placement[1] == scaleset.id for placement in p.placements)), None)
    if project is not None:
        updates["project_id"] = project.id
    return updates
