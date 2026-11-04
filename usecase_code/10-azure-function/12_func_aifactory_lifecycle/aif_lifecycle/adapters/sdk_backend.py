"""One thin L1 esaf call per approved scenario; the L2 API owns orchestration and durable jobs."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any, Callable

from ..application.planner import plan
from ..domain.errors import UnknownId, UpstreamError, UpstreamTimeout, ValidationFailed
from ..domain.ids import parse_any
from ..domain.operation import Preview, StepKind
from ..domain.scenarios import Scenario
from ..ports import Catalog, ConfirmResult, StepRequest
from .api_errors import UpstreamRefused, error_for_status
from .factory_api import bootstrap_config, refuse_deletes, repository_root

# "esaf": the Factory API's /api/v1/esaf job (SDK thin client); the others are jobs an earlier SDK returned.
HANDLE_KINDS = ("esaf", "catalog", "workflow", "factory-deletion")

SCENARIO_METHODS = {
    Scenario.INIT_FACTORY: "init_factory",
    Scenario.ADD_SCALESET: "add_scale_set",
    Scenario.ADD_OR_UPDATE_PROJECT: "upsert_project",
    Scenario.DELETE_PROJECT: "delete_project",
    Scenario.DELETE_SCALESET: "delete_scale_set",
    Scenario.DELETE_FACTORY: "delete_factory",
}


def _translated(call: Callable[[], Any]) -> Any:
    from azurefactory.errors import APIError, AuthError, BlockedError, ConfigError, FailureError, RequestTimeout

    try:
        return call()
    except RequestTimeout:
        raise UpstreamTimeout("The Factory API did not answer in time.") from None
    except (AuthError, BlockedError) as error:
        raise UpstreamRefused(error.message) from None
    except ConfigError as error:
        raise ValidationFailed(error.message, code="sdk-config") from None
    except FailureError as error:
        raise UpstreamError(error.message) from None
    except APIError as error:
        if error.status is None:
            raise UpstreamError(error.message) from None
        raise error_for_status(error.status, error.message) from None


class SdkFactoryBackend:
    name = "sdk"

    def __init__(self, base_url: str, api_key: str | None, folder: str, timeout: float = 30.0, client=None, *,
                 allow_deletes: bool = False, facade=None, clock=None, review_ttl_seconds: int = 600):
        if not folder:
            raise ValidationFailed("AIF_FACTORY_FOLDER (the consumer repo's azurefactory folder on the API host) is required.")
        if facade is None:
            from azurefactory import esaf
            facade = esaf
        if client is None:
            from azurefactory import AzureFactoryClient
            client = _translated(lambda: AzureFactoryClient(base_url=base_url, api_key=api_key, timeout=timeout))
        self.folder = folder
        self.delete_mode = "allow" if allow_deletes else "refuse"
        self._client, self._facade, self._clock = client, facade, clock
        self._ttl = review_ttl_seconds

    def catalog_payload(self) -> dict[str, Any]:
        try:
            return _translated(lambda: self._client.catalog_list(self.folder))
        except UnknownId:
            return {"revision": "", "factories": []}

    def catalog(self) -> Catalog:
        return Catalog.from_api(self.catalog_payload())

    def prepare(self, request: StepRequest) -> Preview:
        refuse_deletes(self.delete_mode, request)
        args, kwargs = self._arguments(request)
        now = self._clock.now() if self._clock else datetime.now(timezone.utc)
        method = SCENARIO_METHODS[request.scenario]
        return Preview(
            plan=[f"Approve {request.scenario.value} for {request.target} through esaf.{method}."],
            affected_resource_groups=[], blockers=[], can_execute=True, expires_at=now.timestamp() + self._ttl,
            backend_ref={"kind": "esaf", "method": method, "args": list(args), "kwargs": kwargs,
                         "scope": dict(request.resolved)},
            warnings=["Scope approval only, not an Azure dry-run: the L1 SDK submits one approved scenario; the L2 API "
                      "owns live reviews and execution. One confirmation authorizes the entire scenario."])

    def confirm(self, request: StepRequest, preview: Preview, phrase: str | None) -> ConfirmResult:
        refuse_deletes(self.delete_mode, request)
        args, kwargs = self._arguments(request)
        method = SCENARIO_METHODS[request.scenario]
        if preview.backend_ref != {"kind": "esaf", "method": method, "args": list(args), "kwargs": kwargs,
                                   "scope": dict(request.resolved)}:
            raise ValidationFailed("The approved scope does not match this scenario.", code="scope-changed")
        # Compare actual identities, not the revision fingerprint of unrelated catalog edits.
        _, current = plan(request.scenario, parse_any(request.target), self.catalog(), request.options,
                          single_scenario=True)
        for key in ("factory_id", "scale_set_id", "project_id"):
            if current.get(key) != request.resolved.get(key):
                raise ValidationFailed("The target's catalog identity changed; prepare a new scope approval.",
                                       code="scope-changed")
        session = self._facade.Session(self.folder, self._client, request.resolved.get("factory_id"))
        # Typed refusals precede acceptance; transport/server failures remain uncertain, never resubmitted.
        handle = _translated(lambda: getattr(self._facade, method)(*args, **kwargs, session=session))
        if not handle.id or handle.kind not in HANDLE_KINDS:
            raise UpstreamError("The SDK returned no usable job handle; reconcile the Factory API before acting again.")
        return ConfirmResult(
            job={"kind": "esaf", "scenario": method, "job_kind": handle.kind, "job_id": handle.id,
                 "factory_id": session.factory},
            targets=[f"api-{handle.kind}-{handle.id}"])

    def job_status(self, job: dict[str, Any]) -> dict[str, Any]:
        if job.get("kind") == "esaf":
            kind, identifier = job["job_kind"], job["job_id"]
        else:
            # Existing persisted jobs remain readable after upgrading; old unconfirmed steps must be re-prepared.
            kind = "workflow" if job.get("kind") == "workflow" else "catalog"
            identifier = job.get("workflow_id") if kind == "workflow" else job.get("job_id")
        if kind not in HANDLE_KINDS or not identifier:
            raise ValidationFailed("The saved SDK job handle is not valid.")
        session = self._facade.Session(self.folder, self._client, job.get("factory_id"))
        handle = self._facade.EsafJob(job.get("scenario", ""), kind, identifier, session)
        return _translated(handle.status)

    def finalize(self, request: StepRequest, succeeded: bool) -> None:
        """The SDK and Factory API own the catalog."""

    def _arguments(self, request: StepRequest) -> tuple[tuple, dict[str, Any]]:
        if request.kind is not StepKind.SCENARIO:
            raise ValidationFailed("This is an old step-by-step SDK operation. Reconcile any running job, then "
                                   "prepare a new single-scenario operation.", code="sdk-operation-upgrade")
        r, options, scenario = request.resolved, request.options, request.scenario
        target = parse_any(request.target)
        if scenario is Scenario.INIT_FACTORY:
            if options.get("wholeWorkflow") is False:
                raise ValidationFailed("The SDK approves the whole scenario; wholeWorkflow cannot be false.")
            body = {"contract_version": 1, "mode": "full-bootstrap", "folder": repository_root(self.folder),
                    "orchestrator": "gha", "config": bootstrap_config(request), "region_short_name": r["region_code"]}
            return (), {"creation_request": body, "poll": 1}
        if scenario is Scenario.ADD_SCALESET:
            spec = options.get("scaleSet")
            if not isinstance(spec, dict) or not isinstance(spec.get("vnetCidr"), str):
                raise ValidationFailed("Send scaleSet {vnetCidr} for esaf.add_scale_set.")
            supported = {"vnetCidr", "maxProjects", "subscriptionId", "tenantId", "orchestrator"}
            if set(spec) - supported:
                raise ValidationFailed("The SDK scaleSet supports only " + ", ".join(sorted(supported)) + ".")
            try:
                network = ipaddress.ip_network(spec["vnetCidr"])
            except ValueError:
                raise ValidationFailed("scaleSet.vnetCidr must be a valid network CIDR.") from None
            if network.version != 4:
                raise ValidationFailed("scaleSet.vnetCidr must be an IPv4 network.")
            maximum = spec.get("maxProjects", 7)
            if type(maximum) is not int or maximum < 1:
                raise ValidationFailed("scaleSet.maxProjects must be a positive whole number.")
            kwargs = {"cidr": str(network), "environment": r["environment"], "max_projects": maximum}
            for external, internal in (("subscriptionId", "subscription_id"), ("tenantId", "tenant_id"),
                                       ("orchestrator", "orchestrator")):
                if external in spec:
                    if not isinstance(spec[external], str) or not spec[external].strip():
                        raise ValidationFailed(f"scaleSet.{external} must be a non-empty string.")
                    kwargs[internal] = spec[external]
            return (target.suffix,), kwargs
        if scenario is Scenario.ADD_OR_UPDATE_PROJECT:
            return (target.number,), {"scale_set": target.scaleset.suffix, "environment": r["environment"],
                                      "settings": request.settings, "display_name": f"Project {target.number}"}
        if scenario is Scenario.DELETE_PROJECT:
            return (target.number,), {"scale_set": target.scaleset.suffix, "environment": r["environment"],
                                      "include_project_subnets": r["include_project_subnets"],
                                      "include_keyvault_and_resource_group": r["include_keyvault_and_resource_group"]}
        if scenario is Scenario.DELETE_SCALESET:
            return (target.suffix,), {"environment": r["environment"]}
        return (), {}
