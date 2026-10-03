"""Plan, what-if and deploy AI Factory health models (project and/or common scope).

plan    read-only: account check, provider check, Resource Graph discovery, rendered summary
deploy  Incremental Bicep deployment per model (+ optional provider registration and pruning)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from uuid import uuid4

from . import __version__
from . import catalog as cat
from . import naming, planner
from .azure import AzureBoundary, default_runner
from .client import HealthModelClient, HealthModelError

TEMPLATE = cat.HEALTHMODEL_ROOT / "bicep" / "main.bicep"
POLICY_KEYS = frozenset({
    "rootUnhealthySeverity", "rootDegradedSeverity", "layerUnhealthySeverity", "layerDegradedSeverity",
    "resourceUnhealthySeverity", "resourceDegradedSeverity",
})
DEFAULT_ALERT_POLICY = {
    "rootUnhealthySeverity": "Sev1", "rootDegradedSeverity": "Sev3", "layerUnhealthySeverity": "Sev2",
    "layerDegradedSeverity": "", "resourceUnhealthySeverity": "", "resourceDegradedSeverity": "",
}


def _workspace(args, resources) -> str | None:
    if args.log_analytics_workspace_id:
        return args.log_analytics_workspace_id
    if not args.log_signals:
        return None
    workspaces = sorted({r.id for r in resources if r.type == "microsoft.operationalinsights/workspaces"})
    if len(workspaces) != 1:
        raise ValueError(f"--log-signals found {len(workspaces)} Log Analytics workspaces in the factory resource "
                         "groups; pass --log-analytics-workspace-id explicitly.")
    return workspaces[0]


def _default_az():
    return default_runner


def _bounded(root: Path, value: str) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("--variables-json must stay inside the consumer root (no parent traversal).")
    if not path.is_file():
        raise ValueError(f"Configuration file not found: {value}")
    return path


def _read_json_file(value: str | None, what: str) -> dict:
    if not value:
        return {}
    try:
        document = json.loads(Path(value).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError(f"Cannot read the {what} file as JSON.") from None
    if not isinstance(document, dict):
        raise ValueError(f"The {what} file must contain a JSON object.")
    return document


def resolve_scope(args) -> naming.FactoryScope:
    if args.variables_json:
        root = Path(args.consumer_root or os.getcwd())
        payload = naming.read_variables(_bounded(root, args.variables_json))
        return naming.from_variables(payload, args.environment, args.project)
    required = ("tenant_id", "subscription", "location", "location_suffix", "project_resource_group")
    missing = [f"--{name.replace('_', '-')}" for name in required if not getattr(args, name)]
    if missing:
        raise ValueError("Pass --variables-json or the explicit scope arguments: " + ", ".join(missing))
    return naming.explicit(
        tenant_id=args.tenant_id, subscription_id=args.subscription, environment=args.environment,
        project_number=args.project, location=args.location, location_suffix=args.location_suffix,
        project_resource_group=args.project_resource_group, common_resource_group=args.common_resource_group or "",
        resource_group_prefix=args.resource_group_prefix or "", resource_group_suffix=args.resource_group_suffix or "",
    )


def bicep_options(args) -> dict:
    options = {}
    policy = _read_json_file(args.alert_policy, "alert policy")
    if policy:
        unknown = set(policy) - POLICY_KEYS
        if unknown:
            raise ValueError(f"Unknown alert policy keys: {sorted(unknown)}")
        for key, value in policy.items():
            if value not in ("", *cat.SEVERITIES):
                raise ValueError(f"{key}: severity must be empty or one of {cat.SEVERITIES}.")
        options["alertPolicy"] = policy
    if args.health_objective is not None:
        if not 0 <= args.health_objective <= 100:
            raise ValueError("--health-objective must be between 0 and 100.")
        options["healthObjective"] = args.health_objective
    if args.action_group_id:
        options["actionGroupIds"] = list(args.action_group_id)
    if args.alert_email:
        options["createActionGroup"] = True
        options["actionGroupEmails"] = list(args.alert_email)
    if len(args.action_group_id or []) + (1 if args.alert_email else 0) > 5:
        raise ValueError("At most five action groups can be notified per entity.")
    if args.no_reader_roles:
        options["assignReaderRoles"] = False
    return options


def _scopes(value: str) -> list[str]:
    return ["project", "common"] if value == "all" else [value]


def run(args, az=None, sleep=time.sleep) -> dict:
    scope = resolve_scope(args)
    catalog = cat.load_catalog()
    overrides = _read_json_file(args.overrides, "overrides")
    options = bicep_options(args)
    azure = AzureBoundary(scope.subscription_id, runner=az or _default_az(), sleep=sleep)
    azure.verify_account(scope.tenant_id)
    provider = azure.provider()
    region, region_reason = naming.health_model_location(
        scope.location, args.health_model_location, supported=provider["regions"] or None)
    registered = provider["registrationState"] == "Registered"
    if args.command == "deploy" and not registered:
        if not args.register_provider:
            raise RuntimeError(f"{scope.subscription_id}: Microsoft.CloudHealth is {provider['registrationState']}. "
                               "Rerun with --register-provider (needs */register/action) or register it once.")
        azure.register_provider()
        registered = True

    results, deployed_models = [], []
    work = Path(args.consumer_root or os.getcwd()) / f".healthmodel-{uuid4().hex[:12]}"
    try:
        for model_scope in _scopes(args.scope):
            if model_scope == "common" and not scope.common_resource_group:
                raise ValueError("The common model needs a common resource group.")
            groups = [scope.project_resource_group, scope.common_resource_group]
            rows = azure.discover(groups, include_health_models=model_scope == "common")
            resources = planner.parse_resources(rows)
            known = {r.id.lower() for r in resources}
            resources += [r for r in deployed_models if r.id.lower() not in known]
            workspace = _workspace(args, resources)
            plan = planner.build_plan(catalog, scope, resources, model_scope=model_scope, overrides=overrides,
                                      log_analytics_workspace_id=workspace)
            document = planner.bicep_parameters(plan, location=region, options=options)
            summary = {**plan.summary(), "location": region, "locationReason": region_reason,
                       "providerRegistration": "Registered" if registered else provider["registrationState"],
                       "apiVersion": catalog["apiVersion"], "logAnalyticsWorkspace": workspace,
                       "alertPolicy": {**DEFAULT_ALERT_POLICY, **options.get("alertPolicy", {})},
                       "azureWritesPerformed": False}
            work.mkdir(exist_ok=True)
            parameters = work / f"{plan.model_name}.parameters.json"
            parameters.write_text(json.dumps(document), encoding="utf-8")
            if args.command == "plan":
                if args.what_if:
                    summary["whatIf"] = (azure.what_if(plan.home_resource_group, TEMPLATE, parameters) if registered
                                         else "skipped: Microsoft.CloudHealth is not registered")
            else:
                name = f"aifactory-{plan.model_name}"[:64]
                azure.deploy(name, plan.home_resource_group, TEMPLATE, parameters)
                model_id = (f"/subscriptions/{scope.subscription_id}/resourceGroups/{plan.home_resource_group}"
                            f"/providers/Microsoft.CloudHealth/healthmodels/{plan.model_name}")
                summary.update(azureWritesPerformed=True, deploymentName=name, healthModelId=model_id)
                client = HealthModelClient(model_id, azure.transport)
                if args.prune:
                    summary["pruned"] = prune(client, plan)
                if not args.no_annotate:
                    annotate(client, plan)
                deployed_models += planner.parse_resources([{
                    "id": model_id, "name": plan.model_name, "type": "microsoft.cloudhealth/healthmodels",
                    "resourceGroup": plan.home_resource_group, "kind": "", "tags": {}}])
            results.append(summary)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    report = {"mode": args.command, "models": results}
    print(json.dumps(report, indent=2, default=sorted))
    if args.command == "plan":
        print("PLAN ONLY: no Azure writes. 'deploy' creates/updates the health model, its entities, "
              "relationships, alert settings and Monitoring Reader role assignments.")
    return report


def prune(client, plan) -> dict:
    stale = client.stale_managed({e.name for e in plan.entities}, {r["name"] for r in plan.relationships})
    for name in stale["relationships"]:
        client.delete_relationship(name)
    for name in stale["entities"]:
        client.delete_entity(name)
    return stale


def annotate(client, plan) -> None:
    run_id = os.environ.get("BUILD_BUILDID") or os.environ.get("GITHUB_RUN_ID") or "local"
    try:
        client.add_annotation("root", {"event": "aifactory-healthmodel-deployment", "tool": f"aifactory-healthmodel {__version__}",
                                       "resources": str(len([e for e in plan.entities if e.role == "resource"])),
                                       "run": run_id[:256]},
                              f"AI Factory health model {plan.model_name} deployed or refreshed.")
    except HealthModelError as error:
        print(f"WARNING: deployment annotation skipped ({error.code}).", file=sys.stderr)


def add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--consumer-root", default=None, help="Repository root that contains --variables-json.")
    parser.add_argument("--variables-json", default=None, help="Persistent AI Factory variables.json (repo-relative).")
    parser.add_argument("--environment", required=True, choices=sorted(naming.ENVIRONMENTS))
    parser.add_argument("--project", required=True, help="Three-digit project number assertion, e.g. 001.")
    explicit = parser.add_argument_group("explicit scope (instead of --variables-json)")
    for name in ("tenant-id", "subscription", "location", "location-suffix", "project-resource-group",
                 "common-resource-group", "resource-group-prefix", "resource-group-suffix"):
        explicit.add_argument(f"--{name}", default=None)


def add_deploy_arguments(parser: argparse.ArgumentParser) -> None:
    add_scope_arguments(parser)
    parser.add_argument("--scope", choices=("project", "common", "all"), default="project",
                        help="project RG model, common RG model, or both (common nests the project model).")
    parser.add_argument("--health-model-location", default=None, help="Override the health model region.")
    parser.add_argument("--overrides", default=None, help="JSON file with signal/profile overrides.")
    parser.add_argument("--alert-policy", default=None, help="JSON file with alert severities (empty disables).")
    parser.add_argument("--health-objective", type=int, default=None)
    parser.add_argument("--action-group-id", action="append", default=[], help="Existing action group ID (repeat).")
    parser.add_argument("--alert-email", action="append", default=[], help="Create an action group e-mailing this address (repeat).")
    parser.add_argument("--no-reader-roles", action="store_true", help="Do not create Monitoring Reader role assignments.")
    parser.add_argument("--log-signals", action="store_true",
                        help="Add Log Analytics query signals (Databricks) using the factory's Log Analytics workspace.")
    parser.add_argument("--log-analytics-workspace-id", default=None, help="Workspace for Log Analytics signals.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="aif-healthmodel", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Read-only discovery and rendered model summary.")
    add_deploy_arguments(plan)
    plan.add_argument("--what-if", action="store_true", help="Also run an ARM what-if (read-only).")
    deploy = commands.add_parser("deploy", help="Deploy or refresh the health model(s).")
    add_deploy_arguments(deploy)
    deploy.add_argument("--register-provider", action="store_true", help="Register Microsoft.CloudHealth if needed.")
    deploy.add_argument("--prune", action="store_true", help="Delete stale entities/relationships created by this tool.")
    deploy.add_argument("--no-annotate", action="store_true", help="Skip the deployment annotation on the root entity.")
    args = parser.parse_args(argv)
    for name, default in (("what_if", False), ("register_provider", False), ("prune", False), ("no_annotate", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    return args


def main(argv=None) -> int:
    try:
        run(parse_args(argv))
        return 0
    except (ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
