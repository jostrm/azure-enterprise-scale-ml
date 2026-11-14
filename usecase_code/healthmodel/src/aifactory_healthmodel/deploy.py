"""Plan, what-if and deploy AI Factory health models from model definitions.

plan    read-only: account check, provider check, one Resource Graph discovery and a rendered
        summary per model (--inventory plans offline from a saved Resource Graph export)
deploy  incremental Bicep deployment per model, nested models first (+ optional provider
        registration and pruning)
models  list and validate model definitions (built in, --definitions-dir, --model FILE)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, naming
from .application.service import HealthModelService, RunRequest
from .bootstrap import Settings, build_registry, create_services
from .domain.definitions import DefinitionRegistry
from .domain.policy import validate_alert_policy
from .infrastructure.azure_cli import AzureCliInfrastructure, default_runner
from .infrastructure.offline import OfflineInfrastructure

SCOPES = {"project": ["project"], "common": ["common"], "all": ["project", "common"]}
CONSUMER_DEFINITIONS = "healthmodels"


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
        options["alertPolicy"] = validate_alert_policy(policy)
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


def definition_dirs(args) -> tuple[Path, ...]:
    """Consumer definition folders: ``<folder of --variables-json>/healthmodels`` when it exists, then every
    ``--definitions-dir`` in order (later folders override earlier keys). Used by every command, so plan,
    deploy and the runtime commands resolve the same definitions."""
    folders: list[Path] = []
    if getattr(args, "variables_json", None):
        root = Path(getattr(args, "consumer_root", None) or os.getcwd())
        convention = _bounded(root, args.variables_json).parent / CONSUMER_DEFINITIONS
        if convention.is_dir():
            folders.append(convention)
    folders.extend(Path(value) for value in getattr(args, "definitions_dir", None) or ())
    # Keep the last occurrence of a repeated folder so the folder given last still wins.
    unique: list[Path] = []
    for folder in reversed(folders):
        if all(folder.resolve() != seen.resolve() for seen in unique):
            unique.append(folder)
    return tuple(reversed(unique))


def _is_definition_file(value: str) -> bool:
    """Definition keys never contain path separators or a .json suffix; anything else is a key."""
    return value.lower().endswith(".json") or "/" in value or "\\" in value


def _resolve_model(registry: DefinitionRegistry, item: str) -> str:
    return registry.load_file(item).key if _is_definition_file(item) else registry.get(item).key


def selected_models(args, registry: DefinitionRegistry) -> list[str]:
    """--scope picks the built-in project/common models; every --model adds a definition key or file."""
    keys = [] if args.scope is None and args.model else list(SCOPES[args.scope or "project"])
    for item in args.model:
        key = _resolve_model(registry, item)
        if key not in keys:
            keys.append(key)
    return keys


def run(args, az=None, sleep=time.sleep, configure=None) -> dict:
    if args.command == "models":
        return list_models(args)
    scope = resolve_scope(args)
    overrides = _read_json_file(args.overrides, "overrides")
    options = bicep_options(args)
    if args.inventory:
        if args.command != "plan":
            raise ValueError("--inventory plans offline; deploy needs Azure access.")
        infrastructure = OfflineInfrastructure.from_file(args.inventory, subscription_id=scope.subscription_id,
                                                         tenant_id=scope.tenant_id)
    else:
        infrastructure = AzureCliInfrastructure(scope.subscription_id, runner=az or _default_az(), sleep=sleep)
    settings = Settings(subscription_id=scope.subscription_id, tenant_id=scope.tenant_id,
                        read_only=args.command == "plan", definitions_dirs=definition_dirs(args), sleep=sleep)
    services = create_services(settings, infrastructure=infrastructure, configure=configure)
    models = selected_models(args, services.get(DefinitionRegistry))
    request = RunRequest(
        mode=args.command, scope=scope, models=tuple(models), overrides=overrides, options=options,
        health_model_location=args.health_model_location, what_if=args.what_if,
        register_provider=args.register_provider, prune=args.prune, annotate=not args.no_annotate,
        log_signals=args.log_signals, workspace_id=args.log_analytics_workspace_id,
        work_root=Path(args.consumer_root or os.getcwd()),
        run_id=os.environ.get("BUILD_BUILDID") or os.environ.get("GITHUB_RUN_ID") or "local")
    report = services.get(HealthModelService).run(request)
    print(json.dumps(report, indent=2, default=sorted))
    if args.command == "plan":
        print("PLAN ONLY: no Azure writes. 'deploy' creates/updates the health model(s), their entities, "
              "relationships, alert settings and Monitoring Reader role assignments.")
    return report


def list_models(args) -> dict:
    registry = build_registry(definition_dirs(args))
    for item in args.model:
        _resolve_model(registry, item)
    report = {"tool": f"aifactory-healthmodel {__version__}",
              "definitions": [definition.describe() for definition in registry.definitions()]}
    print(json.dumps(report, indent=2))
    return report


def add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--consumer-root", default=None, help="Repository root that contains --variables-json.")
    parser.add_argument("--variables-json", default=None, help="Persistent AI Factory variables.json (repo-relative).")
    parser.add_argument("--environment", required=True, choices=sorted(naming.ENVIRONMENTS))
    parser.add_argument("--project", required=True, help="Three-digit project number assertion, e.g. 001.")
    explicit = parser.add_argument_group("explicit scope (instead of --variables-json)")
    for name in ("tenant-id", "subscription", "location", "location-suffix", "project-resource-group",
                 "common-resource-group", "resource-group-prefix", "resource-group-suffix"):
        explicit.add_argument(f"--{name}", default=None)


def add_definition_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", action="append", default=[], metavar="KEY_OR_FILE",
                        help="Model definition key (for example agents) or definition JSON file; repeat for more.")
    parser.add_argument("--definitions-dir", action="append", default=[], metavar="DIR",
                        help="Folder with more model definitions (*.json); later folders override earlier keys. "
                             "<folder of --variables-json>/healthmodels is loaded automatically when it exists.")


def add_deploy_arguments(parser: argparse.ArgumentParser) -> None:
    add_scope_arguments(parser)
    add_definition_arguments(parser)
    parser.add_argument("--scope", choices=tuple(SCOPES), default=None,
                        help="Built-in models: project RG, common RG or both (common nests the project models). "
                             "Default: project, or none when --model is given.")
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
    plan.add_argument("--inventory", default=None,
                      help="Plan offline from a saved Resource Graph inventory (JSON rows) instead of Azure.")
    deploy = commands.add_parser("deploy", help="Deploy or refresh the health model(s).")
    add_deploy_arguments(deploy)
    deploy.add_argument("--register-provider", action="store_true", help="Register Microsoft.CloudHealth if needed.")
    deploy.add_argument("--prune", action="store_true", help="Delete stale entities/relationships created by this tool.")
    deploy.add_argument("--no-annotate", action="store_true", help="Skip the deployment annotation on the root entity.")
    models = commands.add_parser("models", help="List and validate the model definitions.")
    add_definition_arguments(models)
    args = parser.parse_args(argv)
    for name, default in (("what_if", False), ("register_provider", False), ("prune", False), ("no_annotate", False),
                          ("inventory", None)):
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
