"""Command line interface for AzureFactoryClient."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from .client import API_KEY_ENV, API_URL_ENV, AzureFactoryClient, canonical_json_hash, redact_secrets
from .configuration import ConfigurationDraft
from . import enrollment
from .errors import APIError, BlockedError, ConfigError, FailureError, RequestTimeout
from .review import load_receipt as review_load_receipt
from .review import parse_expires_at, validate_preview, write_receipt

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_TIMEOUT = 4
EXIT_FAILURE = 5

REQUIRED_OPENAPI_PATHS = {
    "/health": {"get"},
    "/api/v1/schema": {"get"},
    "/api/v1/projects/load": {"post"},
    "/api/v1/import": {"post"},
    "/api/v1/validation": {"post"},
    "/api/v1/export": {"post"},
    "/api/v1/projects/save": {"post"},
    "/api/v1/projects/load": {"post"},
    "/api/v1/projects/save": {"post"},
    "/api/v1/validation": {"post"},
    "/api/v1/export": {"post"},
    "/api/v1/azure/auth/status": {"post"},
    "/api/v1/factory-catalog": {"get"},
    "/api/v1/factory-catalog/settings": {"get"},
    "/api/v1/factory-catalog/parameters": {"get"},
    "/api/v1/factory-catalog/parameters/prepare": {"post"},
    "/api/v1/factory-catalog/parameters/confirm": {"post"},
    "/api/v1/factory-catalog/prepare": {"post"},
    "/api/v1/factory-catalog/confirm": {"post"},
    "/api/v1/factory-catalog/jobs": {"get"},
    "/api/v1/factory-catalog/jobs/{job_id}": {"get"},
    "/api/v1/factory-catalog/terminal": {"get"},
    "/api/v1/creation/capabilities": {"get"},
    "/api/v1/creation/bootstrap/config": {"post"},
    "/api/v1/creation/bootstrap/prepare": {"post"},
    "/api/v1/creation/bootstrap/start": {"post"},
    "/api/v1/creation/bootstrap/jobs/{job_id}": {"get"},
    "/api/v1/operations/project-deployments": {"get"},
    "/api/v1/operations/project-deployments/plan": {"post"},
    "/api/v1/operations/project-deployments/prepare": {"post"},
    "/api/v1/operations/project-deployments/start": {"post"},
    "/api/v1/operations/project-deployments/terminal": {"get"},
}

REQUIRED_SCHEMAS = {
    "CatalogPrepare",
    "CatalogConfirm",
    "CatalogPreview",
    "CatalogConfirmed",
    "CatalogParameterPrepare",
    "ProjectDeploymentPlanBody",
    "ProjectDeploymentPrepareBody",
    "ProjectDeploymentStartBody",
    "ProjectDeploymentAcknowledgement",
    "BootstrapPrepare",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return _error(130, "Interrupted.")
    except APIError as exc:
        return _error(exc.exit_code, exc.message, exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="azurefactory", description="Safe CLI for the local AzureFactory API.")
    parser.add_argument("--api-url", default=os.getenv(API_URL_ENV), help=f"API base URL (env {API_URL_ENV}, default loopback:8765).")
    parser.add_argument("--api-key", default=os.getenv(API_KEY_ENV), help=f"API key value (env {API_KEY_ENV}); never logged or stored.")
    parser.add_argument("--timeout", type=positive_float, default=30.0, help="Per-request timeout seconds.")
    sub = parser.add_subparsers(dest="command")

    add_simple(sub, "health", cmd_health)
    enroll = sub.add_parser("enrollment", help="Reviewed add-only Azure/provider enrollment; schema-2 consumers only.")
    enroll_sub = enroll.add_subparsers(dest="enrollment_command", required=True)
    for name, handler in (("plan", cmd_enrollment_plan), ("ensure", cmd_enrollment_ensure)):
        command = add_simple(enroll_sub, name, handler)
        for field in ("consumer-root", "factory-id", "scale-set-id", "options"):
            command.add_argument("--" + field, required=name == "plan")
        command.add_argument("--environment", choices=("dev", "stage", "prod"), required=name == "plan")
        command.add_argument("--expected-orchestrator", choices=("ado", "gha"), help="Block a different registered provider.")
        command.add_argument("--acknowledge-exclusive-writer-governance", action="store_true",
                             help="Actual administrator attestation that ALL writers enforce physical leases; not a default.")
        if name == "plan":
            command.add_argument("--save-plan", help="New non-secret, integrity-bound local review file; never overwritten.")
        else:
            command.add_argument("--plan", help="Previously saved --save-plan artifact; scope/options must still match.")
            command.add_argument("--expected-plan", help="Approved plan_hash; required without --plan and full scope flags.")
            command.add_argument("--yes", action="store_true")
            command.add_argument("--save-result", help="New candidate artifact for prepare-binding; requires --plan.")
    binding = add_simple(enroll_sub, "prepare-binding", cmd_enrollment_binding,
                         help="Prepare the exact ensure candidate with the local catalog API; never publish directly.")
    binding.add_argument("--result", required=True, help="Artifact written by enrollment ensure --save-result.")
    binding.add_argument("--expected-revision", required=True, help="Current catalog source_revision, not the enrollment hash.")
    binding.add_argument("--save-receipt", required=True, help="New API receipt for a separate catalog confirm --yes.")
    publish = add_simple(enroll_sub, "publish", cmd_enrollment_publish,
                         help="Confirm only a separately reviewed binding API receipt.")
    add_receipt_and_yes(publish)
    doctor = add_simple(sub, "doctor", cmd_doctor)
    doctor.add_argument("--local-openapi", help="Optional OpenAPI snapshot to compare with the live API.")
    schema = add_simple(sub, "schema", cmd_schema)
    schema.add_argument("--openapi", action="store_true", help="Print live OpenAPI instead of /api/v1/schema.")

    config = sub.add_parser("config", help="Source-preserving JSON legacy-project configuration; never deployment.")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    for name, handler in (("review", cmd_config_review), ("save", cmd_config_save)):
        command = add_simple(config_sub, name, handler)
        command.add_argument("--folder", required=True, help="Exact legacy factory folder on the API host.")
        command.add_argument("--project-number", required=True)
        command.add_argument("--changes-json", help="Local JSON object with only intentional field replacements.")
        command.add_argument("--snapshot-only", action="store_true", help="Do not write pipeline variable files.")
        if name == "save":
            command.add_argument("--expected-review", required=True, help="review_id from the separately approved review.")
            command.add_argument("--yes", action="store_true")

    auth = sub.add_parser("auth", help="Scoped Azure authentication checks.")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_status = add_simple(auth_sub, "status", cmd_auth_status)
    add_auth_scope(auth_status)

    catalog = sub.add_parser("catalog", help="Catalog introspection and receipts.")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = add_simple(catalog_sub, "list", cmd_catalog_list)
    catalog_list.add_argument("--folder", required=True)
    catalog_settings = add_simple(catalog_sub, "settings", cmd_catalog_settings)
    catalog_settings.add_argument("--folder", required=True)
    catalog_settings.add_argument("--factory-id", required=True)
    catalog_settings.add_argument("--scale-set-id")
    catalog_settings.add_argument("--project-id")
    catalog_confirm = add_simple(catalog_sub, "confirm", cmd_catalog_confirm)
    add_receipt_and_yes(catalog_confirm)
    catalog_jobs = add_simple(catalog_sub, "jobs", cmd_catalog_jobs)
    catalog_jobs.add_argument("--folder", required=True)
    catalog_job = add_simple(catalog_sub, "job", cmd_catalog_job)
    catalog_job.add_argument("--folder", required=True)
    catalog_job.add_argument("--job-id", required=True)
    catalog_logs = add_simple(catalog_sub, "logs", cmd_catalog_logs)
    catalog_logs.add_argument("--folder", required=True)
    catalog_logs.add_argument("--job-id", required=True)
    catalog_logs.add_argument("--cursor", type=int, default=0)
    catalog_poll = add_simple(catalog_sub, "poll", cmd_catalog_poll)
    add_poll_args(catalog_poll)
    catalog_poll.add_argument("--folder", required=True)
    catalog_poll.add_argument("--job-id", required=True)

    factory = sub.add_parser("factory", help="Factory create/clone preview commands.")
    factory_sub = factory.add_subparsers(dest="factory_command", required=True)
    factory_create = add_prepare_common(factory_sub, "create", cmd_factory_create)
    factory_create.add_argument("--factory-key")
    factory_create.add_argument("--kind", default="ai", choices=["ai", "robot", "web", "app"])
    factory_create.add_argument("--prefix", required=True)
    factory_create.add_argument("--region", required=True)
    factory_create.add_argument("--aifactory-version")
    add_scaleset_flags(factory_create)
    factory_clone = add_prepare_common(factory_sub, "clone", cmd_factory_clone)
    factory_clone.add_argument("--factory-id", required=True)
    factory_clone.add_argument("--factory-key")
    factory_clone.add_argument("--scale-set-id")
    factory_clone.add_argument("--prefix")
    factory_clone.add_argument("--region")
    factory_clone.add_argument("--include-projects", choices=["none", "all"], default="none")
    factory_clone.add_argument("--aifactory-version")

    scaleset = sub.add_parser("scaleset", help="Scale-set catalog changes.")
    scaleset_sub = scaleset.add_subparsers(dest="scaleset_command", required=True)
    scaleset_add = add_prepare_common(scaleset_sub, "add", cmd_scaleset_add)
    scaleset_add.add_argument("--factory-id", required=True)
    add_scaleset_flags(scaleset_add)

    project = sub.add_parser("project", help="Project catalog changes.")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_add = add_prepare_common(project_sub, "add", cmd_project_add)
    project_add.add_argument("--factory-id", required=True)
    project_add.add_argument("--number", required=True)
    project_add.add_argument("--display-name", default="")
    project_add.add_argument("--placement", action="append", required=True, help="environment=scale_set_uuid; repeat for each placement.")
    project_place = add_prepare_common(project_sub, "add-placements", cmd_project_add_placements)
    project_place.add_argument("--factory-id", required=True)
    project_place.add_argument("--project-id", required=True)
    project_place.add_argument("--placement", action="append", required=True)

    params = sub.add_parser("parameters", help="Typed ARM parameter introspection and editing.")
    params_sub = params.add_subparsers(dest="parameters_command", required=True)
    params_get = add_simple(params_sub, "get", cmd_parameters_get)
    add_catalog_selection(params_get, scale=True)
    params_get.add_argument("--project-id")
    params_get.add_argument("--version-ref")
    params_prepare = add_simple(params_sub, "prepare", cmd_parameters_prepare)
    params_prepare.add_argument("--folder")
    params_prepare.add_argument("--expected-revision")
    params_prepare.add_argument("--save-receipt", help="Write preview receipt JSON for later confirm.")
    params_prepare.add_argument("--factory-id")
    params_prepare.add_argument("--scale-set-id")
    params_prepare.add_argument("--project-id")
    params_prepare.add_argument("--version-ref")
    params_prepare.add_argument("--schema-revision")
    params_prepare.add_argument("--reset-profile", action="store_true")
    params_prepare.add_argument("--request-json", help="Full CatalogParameterPrepare JSON body.")
    params_prepare.add_argument("--template-patch", action="append", help="ParameterPatch JSON file; repeatable.")
    params_prepare.add_argument("--template")
    params_prepare.add_argument("--parameters-json")
    params_prepare.add_argument("--unset", action="append", default=[])
    params_prepare.add_argument("--resource-group-id")
    params_prepare.add_argument("--template-spec-id")
    params_confirm = add_simple(params_sub, "confirm", cmd_parameters_confirm)
    add_receipt_and_yes(params_confirm)

    runtime = sub.add_parser("runtime", help="Catalog runtime deployment through /factory-catalog; never legacy endpoints.")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_deploy = add_prepare_common(runtime_sub, "deploy", cmd_runtime_deploy_prepare)
    runtime_deploy.add_argument("--factory-id", required=True)
    runtime_deploy.add_argument("--scale-set-id", required=True)
    runtime_deploy.add_argument("--project-id")
    runtime_deploy.add_argument("--version-ref")
    runtime_confirm = add_simple(runtime_sub, "confirm", cmd_runtime_confirm)
    add_receipt_and_yes(runtime_confirm)
    runtime_status = add_simple(runtime_sub, "status", cmd_catalog_job)
    runtime_status.add_argument("--folder", required=True)
    runtime_status.add_argument("--job-id", required=True)
    runtime_logs = add_simple(runtime_sub, "logs", cmd_catalog_logs)
    runtime_logs.add_argument("--folder", required=True)
    runtime_logs.add_argument("--job-id", required=True)
    runtime_logs.add_argument("--cursor", type=int, default=0)
    runtime_poll = add_simple(runtime_sub, "poll", cmd_catalog_poll)
    add_poll_args(runtime_poll)
    runtime_poll.add_argument("--folder", required=True)
    runtime_poll.add_argument("--job-id", required=True)

    bootstrap = sub.add_parser("bootstrap", help="Full bootstrap creation flow.")
    bootstrap_sub = bootstrap.add_subparsers(dest="bootstrap_command", required=True)
    add_simple(bootstrap_sub, "capabilities", cmd_bootstrap_capabilities)
    boot_config = add_simple(bootstrap_sub, "config", cmd_bootstrap_config)
    boot_config.add_argument("--state-json", required=True)
    boot_config.add_argument("--mapping-mode", choices=["strict", "common-details"], default="strict",
                             help="common-details returns only account/team defaults; merge into a separate new-factory draft.")
    boot_prepare = add_simple(bootstrap_sub, "prepare", cmd_bootstrap_prepare)
    boot_prepare.add_argument("--save-receipt", help="Write preview receipt JSON for later start.")
    boot_prepare.add_argument("--request-json", help="Full BootstrapPrepare JSON body.")
    boot_prepare.add_argument("--launcher")
    boot_prepare.add_argument("--orchestrator", choices=["ado", "gha"])
    boot_prepare.add_argument("--config-json")
    boot_start = add_simple(bootstrap_sub, "start", cmd_bootstrap_start)
    add_receipt_and_yes(boot_start)
    boot_start.add_argument("--wait", action="store_true")
    add_poll_args(boot_start)
    boot_status = add_simple(bootstrap_sub, "status", cmd_bootstrap_status)
    boot_status.add_argument("--job-id", required=True)
    boot_status.add_argument("--wait", action="store_true")
    add_poll_args(boot_status)

    legacy = sub.add_parser("legacy", help="Legacy project update/promote deployments for legacy roots only; never catalog roots.")
    legacy_sub = legacy.add_subparsers(dest="legacy_command", required=True)
    legacy_list = add_simple(legacy_sub, "list", cmd_legacy_list)
    legacy_list.add_argument("--folder", required=True)
    legacy_plan = add_simple(legacy_sub, "plan", cmd_legacy_plan)
    add_legacy_plan_args(legacy_plan)
    legacy_prepare = add_prepare_common(legacy_sub, "prepare", cmd_legacy_prepare)
    legacy_prepare.add_argument("--draft-id", required=True)
    legacy_prepare.add_argument("--patch", dest="patch", action="store_true", default=None)
    legacy_prepare.add_argument("--no-patch", dest="patch", action="store_false")
    legacy_prepare.add_argument("--aifactory-version")
    legacy_start = add_simple(legacy_sub, "start", cmd_legacy_start)
    add_receipt_and_yes(legacy_start)
    legacy_start.add_argument("--wait", action="store_true")
    add_poll_args(legacy_start)
    legacy_status = add_simple(legacy_sub, "status", cmd_legacy_status)
    legacy_status.add_argument("--folder", required=True)
    legacy_status.add_argument("--job-id", required=True)
    legacy_status.add_argument("--cursor", type=int, default=0)
    legacy_status.add_argument("--wait", action="store_true")
    add_poll_args(legacy_status)

    request = add_simple(sub, "request", cmd_request)
    request.add_argument("method")
    request.add_argument("endpoint")
    request.add_argument("--query", action="append", default=[], help="key=value query value; repeatable.")
    request.add_argument("--body-json", help="JSON request body file.")
    request.add_argument("--body", help="Inline JSON request body.")
    request.add_argument("--write", action="store_true", help="Required for generic unsafe methods.")
    request.add_argument("--yes", action="store_true", help="Required with --write.")
    return parser


def add_simple(sub, name: str, func, **kwargs):
    parser = sub.add_parser(name, **kwargs)
    parser.set_defaults(func=func)
    return parser


def add_prepare_common(sub, name: str, func):
    parser = add_simple(sub, name, func)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--expected-revision")
    parser.add_argument("--save-receipt", help="Write preview receipt JSON for later confirm/start.")
    return parser


def add_auth_scope(parser):
    parser.add_argument("--folder", dest="aifactory_folder")
    parser.add_argument("--factory-id")
    parser.add_argument("--scale-set-id")
    parser.add_argument("--expected-tenant-id")
    parser.add_argument("--expected-subscription-id")


def add_catalog_selection(parser, *, scale: bool):
    parser.add_argument("--folder", required=True)
    parser.add_argument("--factory-id", required=True)
    if scale:
        parser.add_argument("--scale-set-id", required=True)


def add_receipt_and_yes(parser):
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--yes", action="store_true")


def add_poll_args(parser):
    parser.add_argument("--poll-timeout", type=positive_float, default=600.0)
    parser.add_argument("--poll-interval", type=positive_float, default=5.0)


def add_scaleset_flags(parser):
    parser.add_argument("--scale-set-json", help="JSON object or list of CatalogScaleSetInput objects.")
    parser.add_argument("--environment", choices=["dev", "stage", "prod"])
    parser.add_argument("--suffix")
    parser.add_argument("--subscription-id")
    parser.add_argument("--tenant-id")
    parser.add_argument("--orchestrator", choices=["ado", "gha"])
    parser.add_argument("--vnet-cidr")
    parser.add_argument("--max-projects", type=int, default=1)
    parser.add_argument("--common-subnet")
    parser.add_argument("--scoring-subnet")
    parser.add_argument("--powerbi-subnet")
    parser.add_argument("--bastion-subnet")


def add_legacy_plan_args(parser):
    parser.add_argument("--folder", required=True)
    parser.add_argument("--project-number", required=True)
    parser.add_argument("--source-env", choices=["dev", "stage", "prod"], required=True)
    parser.add_argument("--target-env", choices=["dev", "stage", "prod"], required=True)
    parser.add_argument("--operation", choices=["deploy", "update"], default="deploy")
    parser.add_argument("--patch", dest="patch", action="store_true", default=False)
    parser.add_argument("--no-patch", dest="patch", action="store_false")
    parser.add_argument("--aifactory-version")


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def client(args) -> AzureFactoryClient:
    return AzureFactoryClient(args.api_url, args.api_key, args.timeout)


def cmd_health(args):
    return emit(client(args).health())


def cmd_enrollment_plan(args):
    result = enrollment.plan(args)
    return emit(redact_secrets(result, args.api_key),
                EXIT_OK if result.get("can_ensure") is True and not result.get("blockers") else EXIT_BLOCKED)


def cmd_enrollment_ensure(args):
    result = enrollment.ensure(args)
    code = EXIT_OK if result.get("enrollment_complete") is True else EXIT_BLOCKED
    if result.get("reconciliation_required"):
        code = EXIT_FAILURE
    return emit(redact_secrets(result, args.api_key), code)


def cmd_enrollment_binding(args):
    with enrollment.guarded():
        ensure_receipt_target_available(args)
        body = enrollment.binding_request(args.result, args.expected_revision)
        return catalog_prepare_emit(args, body, "enrollment-binding")


def cmd_enrollment_publish(args):
    require_yes(args)
    with enrollment.guarded():
        receipt = load_receipt(args.receipt, client(args), "catalog-confirm", operation_mode="configuration")
        if receipt["operation"] != "enrollment-binding":
            raise ConfigError("Enrollment publish accepts only a separately prepared enrollment binding receipt.")
        result = client(args).catalog_confirm(receipt["folder"], receipt["confirmation_id"])
        return confirmed_emit(result, runtime=False)


def cmd_schema(args):
    c = client(args)
    return emit(c.openapi() if args.openapi else c.schema())


def configuration_draft(args):
    changes = read_json_file(args.changes_json) if args.changes_json else {}
    return ConfigurationDraft.load(client(args), args.folder, args.project_number, changes=changes)


def cmd_config_review(args):
    result = configuration_draft(args).review(write_variables=not args.snapshot_only)
    return emit(result, EXIT_OK if result["can_save"] else EXIT_BLOCKED)


def cmd_config_save(args):
    require_yes(args)
    result = configuration_draft(args).save(args.expected_review, write_variables=not args.snapshot_only)
    return emit(redact_secrets(result, args.api_key))


def cmd_doctor(args):
    c = client(args)
    checks = {"health": None, "openapi": None, "required_paths": [], "required_schemas": [], "contracts": [], "comparison": None}
    checks["health"] = c.health()
    live = c.openapi()
    checks["openapi"] = {"title": live.get("info", {}).get("title"), "version": live.get("info", {}).get("version")}
    missing_paths = _missing_required_paths(live)
    missing_schemas = sorted(REQUIRED_SCHEMAS - set(live.get("components", {}).get("schemas", {})))
    checks["required_paths"] = missing_paths
    checks["required_schemas"] = missing_schemas
    checks["contracts"] = contract_issues(live)
    if args.local_openapi:
        local = read_json_file(args.local_openapi)
        checks["comparison"] = compare_openapi(local, live)
    ok = not missing_paths and not missing_schemas and not checks["contracts"] and not (checks["comparison"] or {}).get("incompatible")
    return emit({"ok": ok, "checks": checks}, EXIT_OK if ok else EXIT_FAILURE)


def cmd_auth_status(args):
    if not any((args.aifactory_folder, args.factory_id, args.scale_set_id, args.expected_tenant_id, args.expected_subscription_id)):
        raise ConfigError("auth status requires an explicit folder, factory/scale-set or expected tenant/subscription scope.")
    return emit(client(args).auth_status(
        aifactory_folder=args.aifactory_folder,
        factory_id=args.factory_id,
        scale_set_id=args.scale_set_id,
        expected_tenant_id=args.expected_tenant_id,
        expected_subscription_id=args.expected_subscription_id,
    ))


def cmd_catalog_list(args):
    return emit(client(args).catalog_list(args.folder))


def cmd_catalog_settings(args):
    return emit(client(args).catalog_settings(args.folder, args.factory_id, args.scale_set_id, args.project_id))


def cmd_catalog_confirm(args):
    require_yes(args)
    receipt = load_receipt(args.receipt, client(args), "catalog-confirm", operation_mode="configuration")
    result = client(args).catalog_confirm(receipt["folder"], receipt["confirmation_id"])
    return confirmed_emit(result, runtime=False)


def cmd_runtime_confirm(args):
    require_yes(args)
    receipt = load_receipt(args.receipt, client(args), "catalog-confirm", operation_mode="runtime")
    result = client(args).catalog_confirm(receipt["folder"], receipt["confirmation_id"])
    return confirmed_emit(result, runtime=True)


def cmd_catalog_jobs(args):
    return emit(client(args).catalog_jobs(args.folder))


def cmd_catalog_job(args):
    result = client(args).catalog_job(args.folder, args.job_id)
    return emit(result, status_exit(result.get("status")))


def cmd_catalog_logs(args):
    result = client(args).catalog_terminal(args.folder, args.job_id, args.cursor)
    return emit(result, status_exit(result.get("status")))


def cmd_catalog_poll(args):
    c = client(args)
    result = poll(lambda: c.catalog_job(args.folder, args.job_id), args.poll_timeout, args.poll_interval, {"succeeded"})
    return emit(result, status_exit(result.get("status")))


def cmd_factory_create(args):
    body = prepare_base(args, "create-factory")
    body.update(factory_kind=args.kind, factory_key=args.factory_key, target_prefix=args.prefix, target_region=args.region,
                aifactory_version=args.aifactory_version, scale_sets=build_scale_sets(args))
    return catalog_prepare_emit(args, body, "factory-create")


def cmd_factory_clone(args):
    body = prepare_base(args, "clone")
    body.update(factory_id=args.factory_id, factory_key=args.factory_key, scale_set_id=args.scale_set_id,
                target_prefix=args.prefix, target_region=args.region, include_projects=args.include_projects,
                aifactory_version=args.aifactory_version)
    return catalog_prepare_emit(args, body, "factory-clone")


def cmd_scaleset_add(args):
    body = prepare_base(args, "create-scale-set")
    body.update(factory_id=args.factory_id, scale_sets=build_scale_sets(args))
    return catalog_prepare_emit(args, body, "scaleset-add")


def cmd_project_add(args):
    body = prepare_base(args, "add-project")
    body.update(factory_id=args.factory_id, project={"number": args.number, "display_name": args.display_name,
                "placements": parse_placements(args.placement)})
    return catalog_prepare_emit(args, body, "project-add")


def cmd_project_add_placements(args):
    body = prepare_base(args, "add-project-placements")
    body.update(factory_id=args.factory_id, project_id=args.project_id, placements=parse_placements(args.placement))
    return catalog_prepare_emit(args, body, "project-add-placements")


def cmd_parameters_get(args):
    return emit(client(args).catalog_parameters(args.folder, args.factory_id, args.scale_set_id, args.project_id, args.version_ref))


def cmd_parameters_prepare(args):
    ensure_receipt_target_available(args)
    if args.request_json:
        body = read_json_file(args.request_json)
        reject_request_json_conflicts(args, body, ("folder", "factory_id", "scale_set_id", "project_id", "version_ref", "expected_revision", "schema_revision"))
    else:
        missing_selection = [name for name in ("folder", "factory_id", "scale_set_id") if not getattr(args, name)]
        if missing_selection:
            raise ConfigError("--request-json is required unless --folder, --factory-id and --scale-set-id are provided.")
        patches = [read_json_file(path) for path in args.template_patch or []]
        if args.template:
            patches.append({
                "template": args.template,
                "parameters": read_json_file(args.parameters_json) if args.parameters_json else {},
                "unset": args.unset,
                "resource_group_id": args.resource_group_id,
                "template_spec_id": args.template_spec_id,
            })
        if not patches:
            raise ConfigError("parameters prepare needs --request-json, --template-patch, or --template.")
        if not args.expected_revision or not args.schema_revision:
            raise ConfigError("parameters prepare requires --expected-revision and --schema-revision unless --request-json is used.")
        body = {
            "folder": args.folder,
            "contract_version": 1,
            "factory_id": args.factory_id,
            "scale_set_id": args.scale_set_id,
            "project_id": args.project_id,
            "version_ref": args.version_ref,
            "expected_revision": args.expected_revision,
            "schema_revision": args.schema_revision,
            "reset_profile": args.reset_profile,
            "templates": [{k: v for k, v in patch.items() if v is not None} for patch in patches],
        }
    result = client(args).parameter_prepare(body)
    maybe_save_receipt(args, result, body, "parameters-confirm", operation="parameters")
    return preview_emit(result)


def cmd_parameters_confirm(args):
    require_yes(args)
    receipt = load_receipt(args.receipt, client(args), "parameters-confirm")
    result = client(args).parameter_confirm(receipt["folder"], receipt["confirmation_id"])
    return confirmed_emit(result, runtime=False)


def cmd_runtime_deploy_prepare(args):
    body = prepare_base(args, "deploy")
    body.update(factory_id=args.factory_id, scale_set_id=args.scale_set_id, project_id=args.project_id, version_ref=args.version_ref)
    return catalog_prepare_emit(args, body, "runtime-deploy")


def cmd_bootstrap_capabilities(args):
    return emit(client(args).creation_capabilities())


def cmd_bootstrap_config(args):
    return emit(client(args).bootstrap_config(read_json_file(args.state_json), mapping_mode=args.mapping_mode))


def cmd_bootstrap_prepare(args):
    ensure_receipt_target_available(args)
    if args.request_json:
        body = read_json_file(args.request_json)
    else:
        if not (args.launcher and args.orchestrator and args.config_json):
            raise ConfigError("bootstrap prepare needs --request-json or --launcher, --orchestrator and --config-json.")
        body = {"launcher": args.launcher, "orchestrator": args.orchestrator, "config": read_json_file(args.config_json)}
    result = client(args).bootstrap_prepare(body)
    maybe_save_receipt(args, result, body, "bootstrap-start", operation="bootstrap")
    return preview_emit(result)


def cmd_bootstrap_start(args):
    require_yes(args)
    c = client(args)
    receipt = load_receipt(args.receipt, c, "bootstrap-start")
    result = c.bootstrap_start(receipt["confirmation_id"])
    if args.wait:
        result = poll(lambda: c.bootstrap_job(result["id"]), args.poll_timeout, args.poll_interval, {"succeeded"})
    return emit(result, status_exit(result.get("status")))


def cmd_bootstrap_status(args):
    c = client(args)
    result = poll(lambda: c.bootstrap_job(args.job_id), args.poll_timeout, args.poll_interval, {"succeeded"}) if args.wait else c.bootstrap_job(args.job_id)
    return emit(result, status_exit(result.get("status")))


def cmd_legacy_list(args):
    return emit(client(args).project_deployments(args.folder))


def cmd_legacy_plan(args):
    validate_legacy_operation(args.operation, args.source_env, args.target_env)
    body = {
        "folder": args.folder,
        "project_number": args.project_number.zfill(3),
        "source_environment": args.source_env,
        "target_environment": args.target_env,
        "operation": args.operation,
        "patch": bool(args.patch),
    }
    if args.aifactory_version is not None:
        body["aifactory_version"] = args.aifactory_version
    result = client(args).project_deployment_plan(body)
    validate_legacy_plan_result(result, body)
    return emit(result)


def cmd_legacy_prepare(args):
    ensure_receipt_target_available(args)
    c = client(args)
    draft = find_legacy_draft(c.project_deployments(args.folder), args.draft_id)
    validate_legacy_draft(draft)
    patch = draft.get("patch") if args.patch is None else bool(args.patch)
    body = {"folder": args.folder, "draft_id": args.draft_id, "patch": patch}
    if args.aifactory_version is not None:
        body["aifactory_version"] = args.aifactory_version
    result = c.project_deployment_prepare(body)
    if result.get("can_execute") is not True:
        return preview_emit(result)
    prepared_draft = find_legacy_draft(c.project_deployments(args.folder), args.draft_id)
    for field in ("project_number", "source_environment", "target_environment", "operation"):
        if prepared_draft.get(field) != draft.get(field):
            raise FailureError("Saved deployment scope changed during preparation.")
    validate_legacy_preview(result, prepared_draft, patch, args.aifactory_version)
    contract = result["deployment_contract"]
    maybe_save_receipt(
        args, result, body, "legacy-start", operation="legacy-project-deployment",
        contract=contract, draft_id=args.draft_id, patch=patch,
        saved_patch=prepared_draft.get("patch"), patch_override=args.patch is not None,
        source_environment=draft.get("source_environment"), target_environment=draft.get("target_environment"),
        saved_aifactory_version=prepared_draft.get("aifactory_version"), version_override=args.aifactory_version is not None,
        aifactory_version=contract.get("aifactory_version"),
        requested_version=contract.get("requested_version"), branch=contract.get("branch"),
        resolved_ref=contract.get("resolved_ref"),
    )
    return preview_emit(result)


def cmd_legacy_start(args):
    require_yes(args)
    c = client(args)
    receipt = load_receipt(args.receipt, c, "legacy-start")
    contract = receipt.get("contract") or {}
    if contract.get("version") != 2:
        raise ConfigError("Legacy start receipt must acknowledge deployment contract version 2.")
    if contract.get("draft_id") != receipt.get("draft_id") or contract.get("patch") is not receipt.get("patch"):
        raise ConfigError("Legacy start receipt contract does not match the reviewed draft/patch binding.")
    draft = find_legacy_draft(c.project_deployments(receipt["folder"]), receipt["draft_id"])
    validate_legacy_draft(draft)
    compare_legacy_receipt_to_draft(receipt, draft)
    result = c.project_deployment_start(receipt["folder"], receipt["confirmation_id"])
    validate_legacy_contract(result.get("deployment_contract"), result, "Legacy start")
    if result.get("deployment_contract") != receipt["preview"]["deployment_contract"]:
        raise FailureError("Legacy start acknowledgement differs from the reviewed operation; inspect the server job before retrying.")
    if args.wait and result.get("job_id"):
        result = poll(lambda: c.project_deployment_terminal(receipt["folder"], result["job_id"]), args.poll_timeout, args.poll_interval, {"submitted"})
    return emit(result, status_exit(result.get("status")))


def cmd_legacy_status(args):
    c = client(args)
    result = poll(lambda: c.project_deployment_terminal(args.folder, args.job_id, args.cursor), args.poll_timeout, args.poll_interval, {"submitted"}) if args.wait else c.project_deployment_terminal(args.folder, args.job_id, args.cursor)
    return emit(result, status_exit(result.get("status")))


def cmd_request(args):
    method = args.method.upper()
    unsafe = method not in {"GET", "HEAD", "OPTIONS"}
    if unsafe and not (args.write and args.yes):
        raise ConfigError("Generic write requests require both --write and --yes.")
    body = None
    if args.body_json:
        body = read_json_file(args.body_json)
    elif args.body:
        body = json.loads(args.body)
    query = dict(parse_key_value(item) for item in args.query)
    result = client(args).request(method, args.endpoint, body=body, query=query)
    exit_code = EXIT_OK
    if unsafe and isinstance(result, dict) and (result.get("can_execute") is False or result.get("blockers")):
        exit_code = EXIT_BLOCKED
    return emit(result, exit_code)


def prepare_base(args, action: str) -> dict[str, Any]:
    return {"folder": args.folder, "contract_version": 1, "action": action, "expected_revision": args.expected_revision}


def build_scale_sets(args) -> list[dict[str, Any]]:
    if args.scale_set_json:
        value = read_json_file(args.scale_set_json)
        return value if isinstance(value, list) else [value]
    required = ["environment", "suffix", "subscription_id", "tenant_id", "orchestrator", "vnet_cidr"]
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        raise ConfigError("Missing scale-set flags: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    network = {"vnet_cidr": args.vnet_cidr, "max_projects": args.max_projects}
    common = {
        "common": args.common_subnet,
        "scoring": args.scoring_subnet,
        "powerbi": args.powerbi_subnet,
        "bastion": args.bastion_subnet,
    }
    if any(common.values()):
        if not all(common.values()):
            raise ConfigError("All four common subnet flags are required when one is supplied.")
        network["common_subnets"] = common
    return [{
        "environment": args.environment,
        "suffix": args.suffix,
        "subscription_id": args.subscription_id,
        "tenant_id": args.tenant_id,
        "orchestrator": args.orchestrator,
        "network": network,
    }]


def parse_placements(values: list[str]) -> list[dict[str, str]]:
    placements = []
    for value in values:
        env, scale_set_id = parse_key_value(value)
        if env not in {"dev", "stage", "prod"}:
            raise ConfigError("Placement environment must be dev, stage or prod.")
        placements.append({"environment": env, "scale_set_id": scale_set_id})
    return placements


def parse_key_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ConfigError(f"Expected key=value, got {value!r}.")
    key, val = value.split("=", 1)
    if not key:
        raise ConfigError("key=value entry has an empty key.")
    return key, val


def catalog_prepare_emit(args, body: dict[str, Any], operation: str) -> int:
    ensure_receipt_target_available(args)
    body = {k: v for k, v in body.items() if v is not None}
    result = client(args).catalog_prepare(body)
    maybe_save_receipt(args, result, body, "catalog-confirm", operation=operation)
    return preview_emit(result)


def preview_emit(result: dict[str, Any]) -> int:
    if not isinstance(result, dict) or "can_execute" not in result:
        return emit({"ok": False, "error": "Malformed preview: missing can_execute.", "preview": result}, EXIT_FAILURE)
    if result.get("can_execute") is not True or result.get("blockers"):
        return emit(result, EXIT_BLOCKED)
    validate_preview(result)
    return emit(result, EXIT_OK)


def confirmed_emit(result: dict[str, Any], *, runtime: bool) -> int:
    if not isinstance(result, dict) or type(result.get("contract_version")) is not int or result["contract_version"] != 1:
        raise FailureError("Confirmation returned an invalid catalog contract. Inspect server state before retrying.")
    if runtime:
        job = result.get("job")
        if not isinstance(job, dict):
            raise FailureError("Runtime confirmation did not return a job. Inspect server state before retrying.")
        return emit(result, status_exit(job.get("status")))
    if not isinstance(result.get("catalog"), dict) or result.get("job") is not None:
        raise FailureError("Configuration confirmation did not return a catalog-only result. Inspect server state before retrying.")
    return emit(result)


def emit(value: Any, exit_code: int = EXIT_OK) -> int:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    return exit_code


def _error(code: int, message: str, exc: APIError | None = None) -> int:
    payload = {"ok": False, "error": {"message": redact_secrets(message, os.getenv(API_KEY_ENV)), "type": type(exc).__name__ if exc else "Error"}}
    if exc and exc.status is not None:
        payload["error"]["status"] = exc.status
    if exc and exc.details is not None:
        payload["error"]["details"] = redact_secrets(exc.details, os.getenv(API_KEY_ENV))
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), file=sys.stderr)
    return code


def read_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc.msg}") from exc
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Cannot read UTF-8 JSON file: {path}") from exc


def maybe_save_receipt(args, preview: dict[str, Any], request_body: dict[str, Any], purpose: str, **extra) -> None:
    path = getattr(args, "save_receipt", None)
    if not path:
        return
    operation = extra.pop("operation", request_body.get("action"))
    write_receipt(path, client=client(args), purpose=purpose, operation=operation,
                  request_body=request_body, preview=preview, **extra)


def load_receipt(path: str, c: AzureFactoryClient, purpose: str, operation_mode: str | None = None) -> dict[str, Any]:
    return review_load_receipt(path, client=c, purpose=purpose, operation_mode=operation_mode)


def parse_datetime(value: str | None) -> datetime:
    return parse_expires_at(value)


def require_yes(args) -> None:
    if not args.yes:
        raise ConfigError("This write requires --yes.")


def ensure_receipt_target_available(args) -> None:
    path = getattr(args, "save_receipt", None)
    if path and os.path.exists(path):
        raise ConfigError(f"Refusing to overwrite existing receipt: {path}")


def reject_request_json_conflicts(args, body: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        arg_value = getattr(args, field, None)
        if arg_value is not None and body.get(field) != arg_value:
            raise ConfigError(f"--request-json conflicts with --{field.replace('_', '-')}.")
    if getattr(args, "reset_profile", False) and body.get("reset_profile") is not True:
        raise ConfigError("--request-json conflicts with --reset-profile.")


def validate_legacy_operation(operation: str, source: str, target: str) -> None:
    if operation == "update" and source != target:
        raise ConfigError("Legacy update requires source and target environment to match.")
    if operation == "deploy":
        order = {"dev": 0, "stage": 1, "prod": 2}
        if order[source] >= order[target]:
            raise ConfigError("Legacy deploy/promote requires a later target environment.")


def validate_legacy_plan_result(result: dict[str, Any], body: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise FailureError("Legacy plan returned a malformed response.")
    for field, request_field in (("project_number", "project_number"), ("source_environment", "source_environment"),
                                 ("target_environment", "target_environment"), ("operation", "operation")):
        if result.get(field) != body.get(request_field):
            raise FailureError(f"Legacy plan response {field} did not match request.")
    if result.get("patch") is not body.get("patch"):
        raise FailureError("Legacy plan response patch did not match request.")
    if body.get("aifactory_version") is not None and result.get("aifactory_version") != body["aifactory_version"]:
        raise FailureError("Legacy plan did not acknowledge the requested source version.")
    contract = result.get("deployment_contract")
    validate_legacy_contract(contract, result, "Legacy plan")


def validate_legacy_contract(contract: Any, draft: dict[str, Any], context: str) -> None:
    if not isinstance(contract, dict) or type(contract.get("version")) is not int or contract["version"] != 2:
        raise FailureError(f"{context} did not include deployment contract version 2.")
    if (not isinstance(draft.get("id"), str) or not draft["id"] or
            draft.get("operation") not in {"deploy", "update"} or
            type(draft.get("patch")) is not bool or type(contract.get("patch")) is not bool):
        raise FailureError(f"{context} contains an invalid draft, operation or patch choice.")
    expected = {
        "draft_id": draft.get("id"),
        "operation": draft.get("operation"),
        "patch": draft.get("patch"),
        "aifactory_version": draft.get("aifactory_version"),
        "requested_version": draft.get("requested_version", ""),
        "branch": draft.get("branch", ""),
        "resolved_ref": draft.get("resolved_ref", ""),
    }
    for field, expected_value in expected.items():
        if expected_value is None and field == "aifactory_version":
            if contract.get(field) is not None:
                raise FailureError(f"{context} contract {field} did not match.")
            continue
        if contract.get(field, "" if field in {"requested_version", "branch", "resolved_ref"} else None) != expected_value:
            raise FailureError(f"{context} contract {field} did not match.")


def find_legacy_draft(drafts_response: dict[str, Any], draft_id: str) -> dict[str, Any]:
    drafts = drafts_response.get("drafts") if isinstance(drafts_response, dict) else None
    if not isinstance(drafts, list):
        raise FailureError("Legacy draft list returned a malformed response.")
    matches = [item for item in drafts if isinstance(item, dict) and item.get("id") == draft_id]
    if len(matches) != 1:
        raise ConfigError("Legacy draft was not found in the selected folder.")
    return matches[0]


def validate_legacy_draft(draft: dict[str, Any]) -> None:
    validate_legacy_contract(draft.get("deployment_contract"), draft, "Saved legacy draft")


def validate_legacy_preview(preview: dict[str, Any], draft: dict[str, Any], patch: bool, version: str | None) -> None:
    if not isinstance(preview, dict):
        raise FailureError("Legacy prepare returned a malformed response.")
    contract = preview.get("deployment_contract")
    expected = dict(draft)
    expected["patch"] = patch
    if version is not None:
        expected["aifactory_version"] = version
    validate_legacy_contract(contract, expected, "Legacy prepare preview")
    if contract.get("draft_id") != draft.get("id") or contract.get("operation") != draft.get("operation"):
        raise FailureError("Legacy prepare acknowledgement did not match the saved draft.")
    if contract.get("patch") is not patch:
        raise FailureError("Legacy prepare acknowledgement did not match the requested patch flag.")


def compare_legacy_receipt_to_draft(receipt: dict[str, Any], draft: dict[str, Any]) -> None:
    contract = receipt.get("contract") or {}
    fields = ("draft_id", "operation", "aifactory_version", "requested_version", "branch", "resolved_ref")
    current = draft.get("deployment_contract", {})
    for field in fields:
        if contract.get(field, "" if field in {"requested_version", "branch", "resolved_ref"} else None) != current.get(field, "" if field in {"requested_version", "branch", "resolved_ref"} else None):
            raise ConfigError("Legacy start receipt no longer matches the saved draft.")
    if receipt.get("saved_patch") is not draft.get("patch"):
        raise ConfigError("Legacy start receipt saved patch binding no longer matches the saved draft.")
    if receipt.get("saved_aifactory_version") != draft.get("aifactory_version"):
        raise ConfigError("Legacy start receipt saved version binding no longer matches the saved draft.")
    if contract.get("patch") is not receipt.get("patch"):
        raise ConfigError("Legacy start receipt contract patch binding is inconsistent.")
    for field in ("source_environment", "target_environment"):
        if receipt.get(field) != draft.get(field):
            raise ConfigError("Legacy start receipt environment binding no longer matches the saved draft.")


def poll(fetch, timeout: float, interval: float, success_statuses: set[str]) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = None
    while True:
        if time.monotonic() >= deadline:
            raise RequestTimeout("Polling timed out before a terminal status. This does not cancel the server operation.", details=last)
        last = fetch()
        if not isinstance(last, dict) or not isinstance(last.get("status"), str):
            raise FailureError("Polling endpoint returned a malformed status response.")
        status = str(last.get("status", "")).lower()
        known = success_statuses | {"queued", "running", "draft", "submitted", "succeeded", "failed", "interrupted"}
        if status not in known:
            raise FailureError(f"Polling endpoint returned unknown status: {status}")
        if status in success_statuses or status in {"failed", "interrupted", "succeeded"}:
            return last
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def status_exit(status: str | None) -> int:
    if not isinstance(status, str):
        return EXIT_FAILURE
    lowered = status.lower()
    if lowered in {"failed", "interrupted"}:
        return EXIT_FAILURE
    if lowered not in {"queued", "running", "draft", "submitted", "succeeded"}:
        return EXIT_FAILURE
    return EXIT_OK


def _missing_required_paths(openapi: dict[str, Any]) -> list[str]:
    paths = openapi.get("paths", {})
    missing = []
    for path, methods in REQUIRED_OPENAPI_PATHS.items():
        actual = {method.lower() for method in paths.get(path, {})}
        for method in methods - actual:
            missing.append(f"{method.upper()} {path}")
    return sorted(missing)


def compare_openapi(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    incompatible = []
    additive = []
    actual_paths = actual.get("paths", {})
    for path, methods in expected.get("paths", {}).items():
        if path not in actual_paths:
            incompatible.append(f"Missing path {path}")
            continue
        for method in methods:
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            method_key = next((m for m in actual_paths[path] if m.lower() == method.lower()), None)
            if method_key is None:
                incompatible.append(f"Missing method {method.upper()} {path}")
                continue
            expected_op = methods[method]
            actual_op = actual_paths[path][method_key]
            incompatible.extend(compare_parameters(path, method, expected_op, actual_op))
            expected_request = request_ref(expected_op)
            actual_request = request_ref(actual_op)
            if expected_request != actual_request:
                incompatible.append(f"{method.upper()} {path} request model changed from {expected_request} to {actual_request}")
            if comparable_schema(expected_op.get("requestBody", {})) != comparable_schema(actual_op.get("requestBody", {})):
                incompatible.append(f"{method.upper()} {path} request body contract changed")
            for status, response in expected_op.get("responses", {}).items():
                if comparable_schema(response) != comparable_schema(actual_op.get("responses", {}).get(status)):
                    incompatible.append(f"{method.upper()} {path} response {status} contract changed")
            if expected_op.get("security") != actual_op.get("security"):
                incompatible.append(f"{method.upper()} {path} security requirement changed")
    expected_schemas = expected.get("components", {}).get("schemas", {})
    actual_schemas = actual.get("components", {}).get("schemas", {})
    for name, schema in expected_schemas.items():
        if name not in actual_schemas:
            incompatible.append(f"Missing schema {name}")
            continue
        incompatible.extend(compare_schema(name, schema, actual_schemas[name]))
        optional_extra, required_extra = added_schema_properties(schema, actual_schemas[name])
        if required_extra:
            incompatible.append(f"Schema {name} adds required properties: {', '.join(required_extra)}")
        if optional_extra:
            additive.append(f"Schema {name} adds optional properties: {', '.join(optional_extra)}")
    return {"incompatible": incompatible, "additive": additive}


def request_ref(operation: dict[str, Any]) -> str | None:
    content = operation.get("requestBody", {}).get("content", {}) if isinstance(operation, dict) else {}
    schema = content.get("application/json", {}).get("schema", {}) if isinstance(content, dict) else {}
    return schema.get("$ref")


def compare_parameters(path: str, method: str, expected_op: dict[str, Any], actual_op: dict[str, Any]) -> list[str]:
    issues = []
    expected = {parameter_key(p): p for p in expected_op.get("parameters", []) if isinstance(p, dict)}
    actual = {parameter_key(p): p for p in actual_op.get("parameters", []) if isinstance(p, dict)}
    for key, parameter in expected.items():
        if key not in actual:
            issues.append(f"{method.upper()} {path} missing parameter {key}")
            continue
        if bool(actual[key].get("required")) != bool(parameter.get("required")):
            issues.append(f"{method.upper()} {path} parameter {key} required flag changed")
        if comparable_schema(parameter.get("schema", {})) != comparable_schema(actual[key].get("schema", {})):
            issues.append(f"{method.upper()} {path} parameter {key} schema changed")
    for key, parameter in actual.items():
        if key not in expected and parameter.get("required"):
            issues.append(f"{method.upper()} {path} adds required parameter {key}")
    return issues


def parameter_key(parameter: dict[str, Any]) -> str:
    return f"{parameter.get('in')}:{parameter.get('name')}"


def compare_schema(name: str, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    issues = []
    expected_required = set(expected.get("required", []))
    actual_required = set(actual.get("required", []))
    missing_required = expected_required - set(actual.get("properties", {}))
    if missing_required:
        issues.append(f"Schema {name} missing required properties: {', '.join(sorted(missing_required))}")
    removed_required = expected_required - actual_required
    if removed_required:
        issues.append(f"Schema {name} removed required markers: {', '.join(sorted(removed_required))}")
    expected_props = expected.get("properties", {})
    actual_props = actual.get("properties", {})
    newly_required = (actual_required - expected_required) & set(expected_props)
    if newly_required:
        issues.append(f"Schema {name} makes existing properties required: {', '.join(sorted(newly_required))}")
    expected_shape = {key: value for key, value in expected.items() if key not in {"properties", "required"}}
    actual_shape = {key: value for key, value in actual.items() if key not in {"properties", "required"}}
    if comparable_schema(expected_shape) != comparable_schema(actual_shape):
        issues.append(f"Schema {name} constraints changed")
    for prop, schema in expected_props.items():
        if prop not in actual_props:
            issues.append(f"Schema {name}.{prop} was removed")
            continue
        if comparable_schema(schema) != comparable_schema(actual_props[prop]):
            issues.append(f"Schema {name}.{prop} changed type/enum/const/ref")
    return issues


def comparable_schema(schema: dict[str, Any]) -> Any:
    if isinstance(schema, list):
        return [comparable_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: comparable_schema(value)
        for key, value in schema.items()
        if key not in {"description", "summary", "title", "example", "examples", "externalDocs"}
    }


def added_schema_properties(expected: dict[str, Any], actual: dict[str, Any]) -> tuple[list[str], list[str]]:
    expected_props = set(expected.get("properties", {}))
    extra = set(actual.get("properties", {})) - expected_props
    actual_required = set(actual.get("required", []))
    return sorted(extra - actual_required), sorted(extra & actual_required)


def contract_issues(openapi: dict[str, Any]) -> list[str]:
    schemas = openapi.get("components", {}).get("schemas", {})
    issues = []
    issues.extend(require_schema_const(schemas, "CatalogPrepare", "contract_version", 1))
    issues.extend(require_schema_const(schemas, "CatalogConfirm", "contract_version", 1))
    issues.extend(require_schema_const(schemas, "CatalogParameterPrepare", "contract_version", 1))
    issues.extend(require_schema_const(schemas, "ProjectDeploymentAcknowledgement", "version", 2))
    issues.extend(require_required(schemas, "ProjectDeploymentAcknowledgement", ["version", "draft_id", "operation", "patch"]))
    issues.extend(require_property_type(schemas, "ProjectDeploymentAcknowledgement", "patch", "boolean"))
    issues.extend(require_property_enum(schemas, "ProjectDeploymentAcknowledgement", "operation", {"deploy", "update"}))
    issues.extend(require_required(schemas, "ProjectDeploymentPlanBody", ["folder", "project_number", "source_environment", "target_environment"]))
    issues.extend(require_property_type(schemas, "ProjectDeploymentPlanBody", "patch", "boolean"))
    issues.extend(require_property_enum(schemas, "ProjectDeploymentPlanBody", "operation", {"deploy", "update"}))
    issues.extend(require_required(schemas, "ProjectDeploymentPrepareBody", ["folder", "draft_id"]))
    issues.extend(require_property_type(schemas, "ProjectDeploymentPrepareBody", "patch", "boolean"))
    expected_refs = {
        ("post", "/api/v1/factory-catalog/prepare"): "#/components/schemas/CatalogPrepare",
        ("post", "/api/v1/factory-catalog/confirm"): "#/components/schemas/CatalogConfirm",
        ("post", "/api/v1/factory-catalog/parameters/prepare"): "#/components/schemas/CatalogParameterPrepare",
        ("post", "/api/v1/operations/project-deployments/plan"): "#/components/schemas/ProjectDeploymentPlanBody",
        ("post", "/api/v1/operations/project-deployments/prepare"): "#/components/schemas/ProjectDeploymentPrepareBody",
        ("post", "/api/v1/operations/project-deployments/start"): "#/components/schemas/ProjectDeploymentStartBody",
    }
    paths = openapi.get("paths", {})
    for (method, path), ref in expected_refs.items():
        actual = request_ref(paths.get(path, {}).get(method, {}))
        if actual != ref:
            issues.append(f"{method.upper()} {path} request model is {actual}, expected {ref}")
    return issues


def require_required(schemas: dict[str, Any], name: str, fields: list[str]) -> list[str]:
    schema = schemas.get(name, {})
    required = set(schema.get("required", []))
    props = set(schema.get("properties", {}))
    return [f"Schema {name} requires {field}" for field in fields if field not in required or field not in props]


def require_schema_const(schemas: dict[str, Any], name: str, field: str, value: Any) -> list[str]:
    schema = schemas.get(name, {}).get("properties", {}).get(field, {})
    if schema.get("const") == value or schema.get("enum") == [value]:
        return []
    return [f"Schema {name}.{field} must be const {value}"]


def require_property_type(schemas: dict[str, Any], name: str, field: str, expected_type: str) -> list[str]:
    actual = schemas.get(name, {}).get("properties", {}).get(field, {})
    if actual.get("type") == expected_type:
        return []
    return [f"Schema {name}.{field} must be type {expected_type}"]


def require_property_enum(schemas: dict[str, Any], name: str, field: str, expected: set[str]) -> list[str]:
    actual = set(schemas.get(name, {}).get("properties", {}).get(field, {}).get("enum", []))
    if actual == expected:
        return []
    return [f"Schema {name}.{field} enum changed"]


if __name__ == "__main__":
    raise SystemExit(main())
