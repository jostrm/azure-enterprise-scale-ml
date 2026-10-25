"""Shared Factory API backend (Template Method): maps steps to Factory API calls; subclasses do the transport.

REST (option 1) and SDK (option 2) inherit this class, so a scenario makes the same API calls whichever transport is
configured; `tests/test_adapter_parity.py` proves it against a fake API. Routes and bodies follow
environment_setup/azurefactory-cli (client.py, catalog_requests.py) and pink's docs/API.md.
"""

from __future__ import annotations

import ntpath
import posixpath
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable

from ..domain.errors import DeletesDisabled, LifecycleError, UnknownId, UpstreamError, ValidationFailed
from ..domain.ids import ScalesetId
from ..domain.operation import Preview, StepKind
from ..domain.scenarios import Scenario, adds_project, enrollment_phrase
from ..ports import Catalog, ConfirmResult, StepRequest
from .api_errors import UpstreamTooOld

RUNTIME_STEPS = {"deploy-common", "deploy-project001", "deploy-project", "delete-project", "delete-scaleset"}
WHOLE_WORKFLOW_SECONDS = 21600  # the full bootstrap's one approval; the API allows 60-86400 s
_JOB_STATES = {"queued": ("queued", None), "running": ("in_progress", None), "succeeded": ("completed", "success"),
               "failed": ("completed", "failure"), "interrupted": ("completed", "failure"),
               # creation workflow states (CreationWorkflowStatus)
               "blocked": ("completed", "failure"), "uncertain": ("completed", "failure"),
               "superseded": ("completed", "failure")}


def job_observation(status: dict[str, Any]) -> dict[str, Any] | None:
    """A Factory API job (or creation workflow) status as a run observation; its latest pipeline run gives the link.

    A whole-workflow creation waits in `awaiting-review` between stages while the API continues by itself; with
    `requires_review` it needs a new human review that this Function does not drive, so the step stops there
    (`action_required`) with the API's message instead of waiting forever.
    """
    state = _JOB_STATES.get(str(status.get("status")))
    if status.get("status") == "awaiting-review":
        state = ("completed", "action_required") if status.get("requires_review") else ("in_progress", None)
    if state is None:
        return None
    run_id, url = None, None
    for run in reversed(status.get("pipeline_runs") or []):
        if isinstance(run, dict) and (run.get("html_url") or run.get("url")):
            url = str(run.get("html_url") or run.get("url"))
            raw = str(run.get("run_id") or run.get("id") or "")
            run_id = int(raw) if raw.isdigit() else None
            break
    return {"status": state[0], "conclusion": state[1], "run_id": run_id, "html_url": url,
            "message": str(status.get("message") or "")}


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


# enroll-scale-set (capability enroll-scale-set-v1): pink's contract for extending a single-writer enrollment.
ENROLL_CAPABILITY = "enroll-scale-set-v1"
ENROLL_MODE = "provider-state-and-arm"
ENROLL_BLOCKED = "Scale-set enrollment blocked: "
BLOB_BLOCKER = "Blob-coordinated factories are not supported yet; nothing was changed."
STATE_REF = "refs/heads/aifactory-state/single-writer-v1"
ENROLL_STATUSES = ("enrolled", "binding-repaired")
ROLE_NAMES = {"b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
              "f58310d9-a9f6-439a-9e8d-f62e7b41a168": "Role Based Access Control Administrator"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HASH = re.compile(r"[0-9a-f]{64}")


def _expires_at(response: dict[str, Any]) -> float:
    try:
        return datetime.fromisoformat(str(response.get("expires_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise UpstreamError("The Factory API review has no valid expires_at.") from None


def enrollment_request(folder: str, request: StepRequest) -> dict[str, Any]:
    """The closed enroll-scale-set prepare body: the exact folder, factory and scale set, nothing else."""
    r = request.resolved
    return {"contract_version": 1, "folder": folder, "factory_id": r["factory_id"], "scale_set_id": r["scale_set_id"]}


def enrollment_preview(request: StepRequest, folder: str, response: Any) -> Preview:
    """The API's enroll-scale-set review as a step preview, checked fail-closed (the API re-verifies on confirm).

    A Blob-coordinated factory has no single-writer enrollment to extend: its review is blocked with exactly
    BLOB_BLOCKER, which becomes a preview marked not needed, so scenario 2 continues with deploy-common. Any other
    blocker blocks the step; a review that does not describe exactly this scale set's enrollment is refused.
    """
    def unsafe(reason: str):
        raise UpstreamError(f"Unsafe or incompatible scale-set enrollment review: {reason}. Nothing was changed.")

    r = request.resolved
    if (not isinstance(response, dict) or response.get("contract_version") != 1
            or ENROLL_CAPABILITY not in (response.get("capabilities") or [])
            or response.get("operation_mode") != ENROLL_MODE):
        unsafe(f"the Factory API must acknowledge {ENROLL_CAPABILITY} in {ENROLL_MODE} mode")
    if (response.get("folder"), response.get("factory_id"), response.get("scale_set_id")) != (
            folder, r["factory_id"], r["scale_set_id"]):
        unsafe("the exact folder, factory and scale set were not preserved")
    blockers, warnings = response.get("blockers"), response.get("warnings")
    if (not isinstance(blockers, list) or not all(isinstance(item, str) and item for item in blockers)
            or not isinstance(warnings, list) or type(response.get("can_execute")) is not bool
            or response["can_execute"] == bool(blockers)):
        unsafe("can_execute must be a boolean that agrees with the blockers")
    warnings = [str(item) for item in warnings]
    expires_at = _expires_at(response)
    base = {"operation": "enroll-scale-set", "folder": folder, "factory_id": r["factory_id"],
            "scale_set_id": r["scale_set_id"]}
    if blockers == [BLOB_BLOCKER]:
        return Preview(plan=[f"Not needed: {BLOB_BLOCKER} A Blob-coordinated factory has no single-writer "
                             "enrollment to extend, so the scale set is deployed without one."],
                       affected_resource_groups=[], blockers=[], can_execute=False, expires_at=expires_at,
                       backend_ref={**base, "not_needed": "Blob-coordinated factory: no single-writer enrollment"},
                       warnings=warnings)
    if blockers:
        return Preview(plan=["Enroll the scale set in the single-writer enrollment (blocked)."],
                       affected_resource_groups=[], blockers=blockers, can_execute=False, expires_at=expires_at,
                       backend_ref=base, warnings=warnings)
    target = ScalesetId.parse(request.target)
    expected = enrollment_phrase(target.factory.prefix, target.suffix)
    if response.get("confirmation_phrase") != expected:
        unsafe(f"the confirmation phrase must be exactly {expected}")
    confirmation_id, preview_hash = response.get("confirmation_id"), response.get("preview_hash")
    if (not isinstance(confirmation_id, str) or not _UUID.fullmatch(confirmation_id)
            or not isinstance(preview_hash, str) or not _HASH.fullmatch(preview_hash)):
        unsafe("missing the exact confirmation identity or server review fingerprint")
    groups, creations = response.get("resource_group_ids"), response.get("resource_group_creations")
    assignments = response.get("role_assignments")
    if (not isinstance(groups, list) or not groups or not all(isinstance(item, str) and item for item in groups)
            or not isinstance(creations, list) or any(item not in groups for item in creations)):
        unsafe("the resource groups to enroll and create must be exact IDs")
    if not isinstance(assignments, list) or any(not isinstance(item, dict) or item.get("scope") not in groups
                                                for item in assignments):
        unsafe("the role assignments must name enrolled resource group scopes")
    audit = response.get("audit_record")
    if (response.get("state_ref") != STATE_REF or not isinstance(audit, str)
            or not audit.startswith(f"scale-set-enrollments/{r['factory_id']}/") or not audit.endswith(".json")):
        unsafe("missing the provider state ref or this factory's audit record")
    revision = response.get("enrollment_revision") or {}
    bindings = [str(item) for item in response.get("bindings") or []]
    identity = response.get("deployment_object_id")
    plan = [f"Enroll scale set {target} in the single-writer enrollment of {response.get('repository')} "
            f"({STATE_REF} at {response.get('provider_head')}), revision {revision.get('from')} -> "
            f"{revision.get('to')}."]
    if revision.get("from") == revision.get("to"):
        plan.append("Binding-only repair: the enrollment already covers these resource groups.")
    plan += [f"Create resource group {group} (tagged)." for group in creations]
    for item in assignments:
        role = str(item.get("role_definition_id") or "")
        name = ROLE_NAMES.get(role.rsplit("/", 1)[-1].lower(), role)
        verb = "Keep the existing" if item.get("exists") is True else "Assign"
        plan.append(f"{verb} {name} role for the deployment identity {identity} on {item['scope']}.")
    if bindings:
        plan.append(f"Re-pin the saved binding(s): {', '.join(bindings)}.")
    plan.append("Azure changes: yes (resource groups or role assignments)." if response.get("azure_writes") is True
                else "Azure changes: none (provider state and binding only).")
    reference = {**base, "confirmation_id": confirmation_id, "preview_hash": preview_hash,
                 "repository": response.get("repository"), "provider_head": response.get("provider_head"),
                 "audit_record": audit}
    return Preview(plan=plan, affected_resource_groups=list(groups), blockers=[], can_execute=True,
                   expires_at=expires_at, confirmation_phrase=expected, backend_ref=reference, warnings=warnings)


def check_enrollment_result(result: Any, reference: dict[str, Any]) -> dict[str, Any]:
    """The confirm result must describe the reviewed enrollment; otherwise its outcome is uncertain (never retried)."""
    keys = ("folder", "factory_id", "scale_set_id", "repository", "audit_record")
    if (not isinstance(result, dict) or result.get("status") not in ENROLL_STATUSES
            or any(result.get(key) != reference.get(key) for key in keys)
            or result.get("previous_head") != reference.get("provider_head") or not isinstance(result.get("head"), str)
            or (result["head"] == result["previous_head"]) != (result["status"] == "binding-repaired")):
        raise UpstreamError("Scale-set enrollment returned an unexpected result. Read the provider state before any "
                            "further action; nothing was retried.")
    return {"kind": "enrollment", "status": result["status"], "head": result["head"],
            "audit_record": result["audit_record"]}


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
                                                     "operation_mode", "workflow_id", "authorization_hash", "folder")
                 if response.get(key) is not None}
    authorization = ((response.get("review") or {}).get("workflow_authorization") or {}).get("authorization_hash")
    if authorization and "authorization_hash" not in reference:  # whole-workflow consent of a creation workflow
        reference["authorization_hash"] = authorization
    return Preview(plan=plan, affected_resource_groups=groups, blockers=[str(item) for item in response.get("blockers") or []],
                   can_execute=response.get("can_execute") is True, expires_at=expires_at,
                   confirmation_phrase=response.get("confirmation_phrase"), backend_ref=reference, warnings=warnings)


def refuse_deletes(delete_mode: str, request: StepRequest) -> None:
    """Real deletes need an explicit opt-in (AIF_DELETES=allow, or AIF_ALLOW_REAL_DELETES=true on the runner)."""
    if request.scenario.destructive and delete_mode != "allow":
        raise DeletesDisabled(f"{request.scenario.value} for {request.target} was not sent to the Factory API: real "
                              "deletes are off here. Set AIF_DELETES=simulate to rehearse it, or allow to delete.")


class FactoryApiBackend(ABC):
    """Steps -> Factory API calls. Subclasses implement the primitive calls (REST or SDK)."""

    name = "api"

    def __init__(self, folder: str, *, allow_deletes: bool = False):
        if not folder:
            raise ValidationFailed("AIF_FACTORY_FOLDER (the consumer repo's azurefactory folder on the API host) is required.")
        self.folder = folder
        self.delete_mode = "allow" if allow_deletes else "refuse"

    # ----- FactoryBackend port -----

    def catalog(self) -> Catalog:
        return Catalog.from_api(self.catalog_payload())

    def catalog_payload(self) -> dict[str, Any]:
        """The API's catalog answer as is (the runner sends it to the Function as the planning snapshot). A consumer
        folder without a catalog yet (404) is an empty catalog, so init-factory can be planned for it."""
        try:
            return self._catalog_list()
        except UnknownId:
            return {"revision": "", "factories": []}

    def prepare(self, request: StepRequest) -> Preview:
        refuse_deletes(self.delete_mode, request)
        if request.kind is StepKind.ENROLL:  # a provider-state operation: no catalog revision in its closed request
            body = enrollment_request(self.folder, request)
            return enrollment_preview(request, self.folder, self._enrollment(lambda: self._enroll_scale_set_prepare(body)))
        try:
            revision = self._catalog_list().get("revision")
        except UnknownId:
            if not _saves_new_factory(request):
                raise
            revision = None  # a new consumer folder has no catalog until the creation saves the factory
        return preview_from_api(self._prepare_call(request, revision))

    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult:
        refuse_deletes(self.delete_mode, request)
        ref = preview.backend_ref
        name = request.step_name
        if request.kind is StepKind.ENROLL:
            result = self._enrollment(lambda: self._enroll_scale_set_confirm({
                "contract_version": 1, "folder": self.folder, "confirmation_id": ref["confirmation_id"],
                "preview_hash": ref["preview_hash"], "confirmation_phrase": phrase}))
            return ConfirmResult(job=check_enrollment_result(result, ref), targets=[])
        if request.kind is StepKind.CONFIGURE:
            if _saves_new_factory(request):
                confirmed = self._creation_confirm(ref["folder"], ref["confirmation_id"])
            else:
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
                # Never an expected_revision: the API refuses a factory creation that selects an existing scope or
                # revision, and the consumer folder's catalog has one as soon as anything was saved there.
                return self._creation_prepare({"contract_version": 1, "mode": "full-bootstrap",
                                               "folder": self._repository_root(), "orchestrator": "gha",
                                               "config": self._bootstrap_config(request),
                                               "region_short_name": r["region_code"]})
            if adds_project(request.scenario, name, r):
                # Scenario 3's settings belong to its new project; scenario 2's project001 starts from defaults.
                settings = request.settings if request.scenario is Scenario.ADD_OR_UPDATE_PROJECT else None
                return self._add_project(r["factory_id"], r["project_number"], f"Project {r['project_number']}",
                                         [{"environment": r["environment"], "scale_set_id": r["scale_set_id"]}],
                                         settings or None, revision)
            if request.scenario is Scenario.ADD_SCALESET:
                return self._add_scaleset(r["factory_id"], [scale_set_body(request, r["suffix"])], revision)
            return self._configure_settings(r["factory_id"], request.settings, r["scale_set_id"], r["project_id"], revision)
        if request.kind is StepKind.BOOTSTRAP:
            if name != "bootstrap":
                raise ValidationFailed("With the Factory API, init-factory runs as one whole-workflow approval of the "
                                       "full bootstrap; send wholeWorkflow: true.")
            return self._workflow_prepare(self._workflow_request(request, revision))
        if name == "deploy-common":
            return self._deploy(deploy_request(self.folder, r["factory_id"], r["scale_set_id"], None, revision))
        if name in ("deploy-project001", "deploy-project"):
            if not r.get("project_id"):
                raise ValidationFailed(f"{request.target} has no catalog project {r.get('project_number', '001')} placed on "
                                       "the selected scale set, so there is no project to deploy; add the project first.")
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

    def _bootstrap_config(self, request: StepRequest) -> dict[str, Any]:
        """The caller's full bootstrap configuration, pinned to the FactoryId so the saved scope can't drift from it.
        The creation and its workflow send the same values: the API refuses a workflow whose settings differ."""
        config = request.options.get("bootstrapConfig")
        if not isinstance(config, dict):
            raise ValidationFailed("Send bootstrapConfig (the API's Full bootstrap configuration) for init-factory.")
        r = request.resolved
        if r.get("environment", "dev") != "dev":
            raise ValidationFailed("A full bootstrap creates the factory's dev scale set; initialize it with a dev "
                                   "FactoryId and add other environments as scale sets.")
        return {**config, "factory_prefix": r["prefix"], "location": r["region"], "scale_set_number": r.get("suffix", "001")}

    def _workflow_request(self, request: StepRequest, revision: str | None) -> dict[str, Any]:
        r = request.resolved
        scope = {"folder": self.folder, "factory_id": r["factory_id"], "scale_set_id": r["scale_set_id"]}
        if r.get("project_id"):
            scope["project_id"] = r["project_id"]
        return {"contract_version": 1, "operation": "create-factory", "execution_mode": "privileged-bootstrap",
                "creation_mode": "full-bootstrap", "scope": scope, "expected_revision": revision,
                "bootstrap_config": self._bootstrap_config(request), "approval_mode": "whole-workflow",
                "authorization_valid_for_seconds": WHOLE_WORKFLOW_SECONDS}

    @staticmethod
    def _enrollment(call: Callable[[], Any]) -> Any:
        """An API without the enroll-scale-set routes answers 404/405 without the operation's own detail."""
        try:
            return call()
        except LifecycleError as error:
            status = getattr(error, "upstream_status", None)
            if status in (404, 405) and not error.detail.startswith(ENROLL_BLOCKED):
                raise UpstreamTooOld(f"Factory API too old for enroll-scale-set (HTTP {status}): update the Factory "
                                     f"API on its host to a version with {ENROLL_CAPABILITY}. Nothing was "
                                     "changed.") from None
            raise

    def _repository_root(self) -> str:
        """The consumer repository (the parent of its azurefactory folder), as the creation routes take it."""
        paths = ntpath if ("\\" in self.folder or ntpath.splitdrive(self.folder)[0]) else posixpath
        trimmed = self.folder.rstrip("\\/")
        return paths.dirname(trimmed) if paths.basename(trimmed).lower() == "azurefactory" else trimmed

    # ----- primitives (transport) -----

    @abstractmethod
    def _catalog_list(self) -> dict[str, Any]: ...

    @abstractmethod
    def _creation_prepare(self, body): ...

    @abstractmethod
    def _creation_confirm(self, folder, confirmation_id): ...

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

    @abstractmethod
    def _enroll_scale_set_prepare(self, body): ...

    @abstractmethod
    def _enroll_scale_set_confirm(self, body): ...


def _saves_new_factory(request: StepRequest) -> bool:
    return request.scenario is Scenario.INIT_FACTORY and request.kind is StepKind.CONFIGURE


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
