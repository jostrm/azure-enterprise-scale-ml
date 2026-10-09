"""Facade over planning and deployment of any number of health models in one run."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from .. import naming
from ..domain.definitions import DefinitionRegistry, ModelDefinition
from ..domain.overrides import OverrideSet
from ..domain.plan import ModelPlan
from ..domain.resources import DiscoveredResource, health_model_resource, parse_resources
from .commands import (AnnotateModelCommand, Command, CommandInvoker, DeployModelCommand, LazyClient,
                       PruneModelCommand, RegisterProviderCommand)
from .events import EventBus, ModelPlanned, RunCompleted, RunStarted
from .parameters import BicepParameterRenderer
from .ports import (AccountVerifier, ArmTransport, ClientFactory, ProviderRegistrar, ResourceDiscovery,
                    TemplateDeployer)

MODES = ("plan", "deploy")
LOG_ANALYTICS_TYPE = "microsoft.operationalinsights/workspaces"


@dataclass(frozen=True)
class RunRequest:
    mode: str
    scope: naming.FactoryScope
    models: tuple[str, ...] = ("project",)
    overrides: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    health_model_location: str | None = None
    what_if: bool = False
    register_provider: bool = False
    prune: bool = False
    annotate: bool = True
    log_signals: bool = False
    workspace_id: str | None = None
    work_root: Path = field(default_factory=Path.cwd)
    run_id: str = "local"


class HealthModelService:
    """One entry point (Facade) for: verify account, provider gate, region, discovery once,
    plan every requested definition in nesting order, render parameters, what-if or deploy."""

    def __init__(self, *, registry: DefinitionRegistry, renderer: BicepParameterRenderer, account: AccountVerifier,
                 providers: ProviderRegistrar, discovery: ResourceDiscovery, deployer: TemplateDeployer,
                 transport: ArmTransport, client_factory: ClientFactory, events: EventBus, invoker: CommandInvoker,
                 template: Path, supports_writes: bool = True, read_only: bool = False):
        self.registry, self.renderer = registry, renderer
        self.account, self.providers, self.discovery, self.deployer = account, providers, discovery, deployer
        self.transport, self.client_factory = transport, client_factory
        self.events, self.invoker = events, invoker
        self.template, self.supports_writes, self.read_only = template, supports_writes, read_only

    def run(self, request: RunRequest) -> dict:
        if request.mode not in MODES:
            raise ValueError("mode must be plan or deploy.")
        if not request.models:
            raise ValueError("Select at least one model definition.")
        order = self.registry.deployment_order(request.models)
        self._preflight(order, request)
        if request.mode == "deploy" and self.read_only:
            raise RuntimeError("These services were composed read-only (plan); compose them with read_only=False "
                               "to deploy.")
        if request.mode == "deploy" and not self.supports_writes:
            raise RuntimeError("This run plans from an offline inventory; deploy needs Azure access.")
        scope = request.scope
        self.events.publish(RunStarted(request.mode, tuple(order), scope.subscription_id))
        self.account.verify_account(scope.tenant_id)
        provider = self.providers.provider()
        region, region_reason = naming.health_model_location(
            scope.location, request.health_model_location, supported=provider["regions"] or None)
        registered = provider["registrationState"] == "Registered"
        writes = len(self.invoker.history)
        if request.mode == "deploy" and not registered:
            if not request.register_provider:
                raise RuntimeError(f"{scope.subscription_id}: Microsoft.CloudHealth is {provider['registrationState']}. "
                                   "Rerun with --register-provider (needs */register/action) or register it once.")
            self.invoker.execute(RegisterProviderCommand(self.providers, scope.subscription_id))
            registered = True

        nests = any(self.registry.get(key).nests for key in order)
        rows = self.discovery.discover([scope.project_resource_group, scope.common_resource_group],
                                       include_health_models=nests)
        resources = parse_resources(rows)
        workspace = self._workspace(request, resources)
        known = {r.id.lower() for r in resources}
        planned_models: list[DiscoveredResource] = []
        results = []
        work = Path(request.work_root) / f".healthmodel-{uuid4().hex[:12]}"
        try:
            for key in order:
                extra = [m for m in planned_models if m.id.lower() not in known]
                plan = self.registry.plan(key, scope, [*resources, *extra], overrides=request.overrides,
                                          workspace=workspace)
                document = self.renderer.render(plan, location=region, options=request.options)
                summary = {**plan.summary(), "definition": key, "location": region, "locationReason": region_reason,
                           "providerRegistration": "Registered" if registered else provider["registrationState"],
                           "apiVersion": self.registry.catalog.api_version, "logAnalyticsWorkspace": workspace,
                           "alertPolicy": self.renderer.alert_policy(plan, request.options),
                           "azureWritesPerformed": False}
                work.mkdir(exist_ok=True)
                parameters = work / f"{plan.model_name}.parameters.json"
                parameters.write_text(json.dumps(document), encoding="utf-8")
                deploy, *follow_up = commands = self._commands(plan, parameters, request)
                summary["writes"] = [command.describe() for command in commands]
                self.events.publish(ModelPlanned(key, plan.model_name, len(plan.entities), summary["signals"],
                                                 tuple(plan.warnings)))
                if request.mode == "plan":
                    if request.what_if:
                        summary["whatIf"] = (self.deployer.what_if(plan.home_resource_group, self.template, parameters)
                                             if registered else "skipped: Microsoft.CloudHealth is not registered")
                else:
                    self.invoker.execute(deploy)
                    summary.update(azureWritesPerformed=True, deploymentName=deploy.deployment_name,
                                   healthModelId=plan.model_id)
                    for command in follow_up:
                        outcome = self.invoker.execute(command)
                        if isinstance(command, PruneModelCommand):
                            summary["pruned"] = outcome
                planned_models.append(health_model_resource(plan.model_id, plan.model_name, plan.home_resource_group))
                results.append(summary)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.events.publish(RunCompleted(request.mode, tuple(order), len(self.invoker.history) - writes))
        return {"mode": request.mode, "models": results}

    def _preflight(self, order: list[str], request: RunRequest) -> None:
        """Validate every model of the run before the first Azure call, so no run stops half deployed."""
        overrides = OverrideSet.parse(request.overrides, self.registry.catalog)
        ModelDefinition.validate_workspace(request.workspace_id)
        self.renderer.validate_options(request.options)
        for key in order:
            self.registry.get(key).preflight(request.scope, overrides)

    def _commands(self, plan: ModelPlan, parameters: Path, request: RunRequest) -> list[Command]:
        client = LazyClient(lambda: self.client_factory(plan.model_id, self.transport))
        commands: list[Command] = [DeployModelCommand(self.deployer, plan, self.template, parameters)]
        if request.prune:
            commands.append(PruneModelCommand(lambda: client, plan))
        if request.annotate:
            commands.append(AnnotateModelCommand(lambda: client, plan, request.run_id, self.events))
        return commands

    @staticmethod
    def _workspace(request: RunRequest, resources: list[DiscoveredResource]) -> str | None:
        if request.workspace_id:
            return request.workspace_id
        if not request.log_signals:
            return None
        workspaces = sorted({r.id for r in resources if r.type == LOG_ANALYTICS_TYPE})
        if len(workspaces) != 1:
            raise ValueError(f"--log-signals found {len(workspaces)} Log Analytics workspaces in the factory resource "
                             "groups; pass --log-analytics-workspace-id explicitly.")
        return workspaces[0]
