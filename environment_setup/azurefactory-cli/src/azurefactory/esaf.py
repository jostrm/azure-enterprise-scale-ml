"""ESAF - Enterprise Scale Azure Factory: the six lifecycle scenarios, one call each.

    from azurefactory import esaf

    esaf.init_factory()                                      # Scenario 1: submit the folder's saved factory draft
    esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16")   # Scenario 2: the VNet range; the pipeline makes subnets
    esaf.upsert_project("002", "dev")                        # Scenario 3: add or update a project and deploy it
    esaf.delete_project("002", "dev")                        # Scenario 4
    esaf.delete_scale_set("002", "dev")                      # Scenario 5
    esaf.delete_factory()                                    # Scenario 6
    job.wait()                                               # reads the job every second until it ends

Connection, set once: the environment variables ESAF_FOLDER (the azurefactory folder on the API host),
AIFACTORY_API_URL and AIFACTORY_API_KEY, or esaf.connect(folder=..., url=..., api_key=..., factory=...). The factory
is needed only when the folder holds more than one.

Environment (dev, stage or prod) is required on scale-set and project scenarios: the same suffix or project number
can exist in several environments, and a delete must never reach another one.

Each lifecycle call is one POST to the Factory API's /api/v1/esaf/<scenario> route, which runs the scenario as a resilient
server-side job and answers 202 with a job id. Calling the method is the approval, so call it only for what you mean
to change. apply_project remains an alias of upsert_project.

export_allowed_projects(factory, project_numbers) is instead a read-only API export returning an EsafExportPackage.
It uses the same connection, never starts a job, and writes nothing until package.save(destination) is called.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from .client import AzureFactoryClient
from .errors import APIError, ConfigError
from .export_package import EsafExportPackage

__all__ = ["connect", "init_factory", "add_scale_set", "upsert_project", "apply_project", "delete_project",
           "delete_scale_set", "delete_factory", "export_allowed_projects", "EsafExportPackage", "EsafJob", "Session"]

ENVIRONMENTS = ("dev", "stage", "prod")
ACTIVE = {"queued", "running", "pending", "accepted", "preparing", "confirming", "retrying"}


@dataclass
class Session:
    folder: str
    client: Any
    factory: str | None = None  # factory key or id; default: the folder's only factory

    def export_allowed_projects(self, factory: str, project_numbers: list[str] | tuple[str, ...]) -> EsafExportPackage:
        """Export through this connection, using the explicitly selected factory."""
        return self.client.esaf_export_allowed_projects(self.folder, factory, project_numbers)


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
    """A started scenario. status() reads it once; wait() reads it every `poll` seconds until it ends."""
    scenario: str
    kind: str  # esaf; catalog | factory-deletion | workflow for jobs an earlier SDK stored
    id: str | None
    session: Session
    result: dict | None = None

    def status(self) -> dict:
        client, folder = self.session.client, self.session.folder
        if self.kind == "esaf":
            return client.esaf_job(folder, self.id)
        if self.kind == "catalog":
            state = client.catalog_job(folder, self.id)
        elif self.kind == "factory-deletion":
            state = client.delete_aifactory_status(folder, self.id)
        else:
            state = client.creation_workflow_status(folder, self.id)
        return state["job"] if isinstance(state.get("job"), dict) else state

    def wait(self, timeout: float = 8 * 3600, poll: float = 1) -> dict:
        deadline = time.monotonic() + timeout
        transient_until = None
        while True:
            try:
                state = self.status()
                transient_until = None
            except APIError as error:
                # A status read can meet a transient 5xx (a record being replaced on Windows) while the job
                # keeps running; keep polling for up to a minute, then let the error surface.
                if getattr(error, "status", None) is None or error.status < 500:
                    raise
                transient_until = transient_until or time.monotonic() + 60
                if time.monotonic() > transient_until:
                    raise
                time.sleep(poll)
                continue
            continuing = (self.kind == "workflow" and state.get("status") == "awaiting-review"
                          and state.get("requires_review") is False)
            if (state.get("status") not in ACTIVE and not continuing) or time.monotonic() > deadline:
                self.result = state
                return state
            time.sleep(poll)


def _session(session: Session | None) -> Session:
    return session or _default or connect()


def export_allowed_projects(factory: str, project_numbers: list[str] | tuple[str, ...], *,
                            session: Session | None = None) -> EsafExportPackage:
    """Return a server-built ZIP for selected projects; save(destination) writes it explicitly.

    Uses the connected API folder, URL and credentials. Select a canonical factory key or UUID and 1 to 200 unique
    existing project numbers from '000' to '999'; registration is checked by the API, not inferred locally.
    The package's project-lock is a local selection restriction, not an Azure permission grant.
    """
    return _session(session).export_allowed_projects(factory, project_numbers)


def _environment(environment: str) -> str:
    if environment not in ENVIRONMENTS:
        raise ConfigError("environment must be dev, stage or prod, not " + repr(environment) + ".")
    return environment


def _submit(scenario: str, route: str, fields: dict, *, wait: bool, poll: float, session: Session | None) -> EsafJob:
    s = _session(session)
    body = {"folder": s.folder, "approved": True, **({"factory": s.factory} if s.factory else {}),
            **{key: value for key, value in fields.items() if value is not None}}
    accepted = s.client.esaf_submit(route, body)
    job = EsafJob(scenario, "esaf", accepted.get("job_id"), s)
    if wait:
        job.wait(poll=poll)
    return job


# The six scenarios -------------------------------------------------------------------------------------------------
def init_factory(*, creation_request: dict | None = None, scale_set_settings: dict | None = None,
                 project_settings: dict | None = None, retries: int | None = None, wait: bool = False,
                 poll: float = 1, session: Session | None = None) -> EsafJob:
    """Scenario 1: submit the connected folder's saved factory draft as one whole-workflow approval.

    creation_request (the creation API's full-bootstrap body) saves the factory and starts it in one call instead.
    With it, scale_set_settings (the first Dev scale set) and project_settings (the initial project:
    enableFactoryChatAgent, enableAIFactoryMCP, addAIFactoryMCP2APIM, ...) are saved before anything deploys, so one
    call creates a factory on a BYO VNet or BYO subnets with its project switches set. One JSON file can hold all
    three: esaf.init_factory(**json.load(file)).

    scale_set_settings by example. Automated networking: leave it out. BYO VNet: byoVnetResourcegroupName and
    byoVnetName. BYO subnets: also enableByoSubnets=True and the subnet names (subnetCommon, subnetProjGenAI, ...).
    The Factory API maps the three friendly names to the wizard's keys (vnetResourceGroup_param, vnetNameFull_param,
    BYO_subnets), which still work.
    """
    return _submit("init_factory", "init-factory", {
        "creation_request": creation_request, "scale_set_settings": scale_set_settings,
        "project_settings": project_settings, "retries": retries}, wait=wait, poll=poll, session=session)


def add_scale_set(scale_set: str, environment: str, *, cidr: str | None = None, max_projects: int | None = None,
                  subscription_id: str | None = None, tenant_id: str | None = None, orchestrator: str | None = None,
                  settings: dict | None = None, version_ref: str | None = None, retries: int | None = None,
                  wait: bool = False, poll: float = 1, session: Session | None = None) -> EsafJob:
    """Scenario 2: register scale set <scale_set> in <environment> (if new), enroll it and deploy its common.

    cidr is the new scale set's VNet range; the pipeline computes the subnets (with BYOSubnet they already exist).
    Tenant, subscription and orchestrator default to the environment's existing scale set.
    settings (flat wizard keys, e.g. byoVnetResourcegroupName, byoVnetName, enableByoSubnets, the subnet names,
    byoASEv3, byoAseFullResourceId) are saved at scale-set scope before the deploy. The Factory API maps the three
    friendly BYO names to vnetResourceGroup_param, vnetNameFull_param and BYO_subnets, which still work.
    """
    return _submit("add_scale_set", "add-scale-set", {
        "scale_set": scale_set, "environment": _environment(environment), "cidr": cidr,
        "max_projects": max_projects, "subscription_id": subscription_id, "tenant_id": tenant_id,
        "orchestrator": orchestrator, "settings": settings, "version_ref": version_ref, "retries": retries},
        wait=wait, poll=poll, session=session)


def upsert_project(project: str, environment: str, *, scale_set: str | None = None, settings: dict | None = None,
                   display_name: str | None = None, version_ref: str | None = None, retries: int | None = None,
                   wait: bool = False, poll: float = 1, session: Session | None = None) -> EsafJob:
    """Scenario 3: add project <project> in <environment> (or update it), enroll its scale set and deploy it.

    scale_set is needed only when the environment has more than one scale set.
    """
    return _submit("upsert_project", "upsert-project", {
        "project": project, "environment": _environment(environment), "scale_set": scale_set,
        "settings": settings, "display_name": display_name, "version_ref": version_ref, "retries": retries},
        wait=wait, poll=poll, session=session)


apply_project = upsert_project


def delete_project(project: str, environment: str, *, scale_set: str | None = None,
                   include_project_subnets: bool | None = None, include_keyvault_and_resource_group: bool | None = None,
                   version_ref: str | None = None, retries: int | None = None, wait: bool = False, poll: float = 1,
                   session: Session | None = None) -> EsafJob:
    """Scenario 4: delete project <project>'s resources in <environment> (its resource group by default)."""
    return _submit("delete_project", "delete-project", {
        "project": project, "environment": _environment(environment), "scale_set": scale_set,
        "include_project_subnets": include_project_subnets,
        "include_keyvault_and_resource_group": include_keyvault_and_resource_group,
        "version_ref": version_ref, "retries": retries}, wait=wait, poll=poll, session=session)


def delete_scale_set(scale_set: str, environment: str, *, version_ref: str | None = None,
                     retries: int | None = None, wait: bool = False, poll: float = 1,
                     session: Session | None = None) -> EsafJob:
    """Scenario 5: delete scale set <scale_set>'s registered resources in <environment>."""
    return _submit("delete_scale_set", "delete-scale-set", {
        "scale_set": scale_set, "environment": _environment(environment), "version_ref": version_ref,
        "retries": retries}, wait=wait, poll=poll, session=session)


def delete_factory(*, version_ref: str | None = None, retries: int | None = None, wait: bool = False,
                   poll: float = 1, session: Session | None = None) -> EsafJob:
    """Scenario 6: delete the whole factory (every registered resource; shared hubs and subscriptions stay)."""
    return _submit("delete_factory", "delete-factory", {"version_ref": version_ref, "retries": retries},
                   wait=wait, poll=poll, session=session)
