"""Two-phase direct API example: configure one AI factory with default project001, never deploy."""

import argparse
import json
from pathlib import Path, PureWindowsPath
import re
import sys
from uuid import UUID

from azurefactory import (
    APIError, AzureFactoryClient, ConfigError, FailureError,
    load_receipt, validate_preview, write_receipt,
)
from azurefactory.client import redact_secrets
from inspect_factory import exactly_one


def require_uuid(value):
    try:
        identifier = UUID(value)
        if not identifier.int or str(identifier) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise FailureError("Expected a nonzero canonical UUID in the selected scope.") from None
    return value


def check_request(body):
    allowed = {
        "folder", "contract_version", "action", "factory_kind", "factory_key",
        "target_prefix", "target_region", "aifactory_version", "scale_sets",
    }
    if not isinstance(body, dict) or set(body) != allowed:
        raise ConfigError("Use the rendered 01-create-factory.json request; no extra fields or project overrides.")
    if (type(body["contract_version"]) is not int or body["contract_version"] != 1
            or body["action"] != "create-factory" or body["factory_kind"] != "ai"):
        raise ConfigError("This example accepts only AI create-factory configuration, contract v1.")
    if not isinstance(body["folder"], str) or not PureWindowsPath(body["folder"]).is_absolute():
        raise ConfigError("folder must be an absolute Windows path on the API host.")
    for name, pattern in (
        ("factory_key", r"[a-z][a-z0-9-]{1,79}"),
        ("target_prefix", r"[a-z][a-z0-9-]{1,19}"),
        ("target_region", r"[a-z][a-z0-9]{1,49}"),
        ("aifactory_version", r"(?:main|[1-9][0-9]{2,})"),
    ):
        if not isinstance(body[name], str) or not re.fullmatch(pattern, body[name]):
            raise ConfigError(f"Supply a valid {name}; do not leave template placeholders.")
    if body["aifactory_version"] != "main" and int(body["aifactory_version"]) < 125:
        raise ConfigError("Registered creation requires version 125 or newer, or main.")
    scales = body["scale_sets"]
    if not isinstance(scales, list) or len(scales) != 1 or not isinstance(scales[0], dict):
        raise ConfigError("This quickstart requires one DEV/001 scale set.")
    scale = scales[0]
    if (set(scale) != {"environment", "suffix", "subscription_id", "tenant_id", "orchestrator", "network"}
            or scale["environment"] != "dev" or scale["suffix"] != "001"
            or scale["orchestrator"] not in ("ado", "gha")):
        raise ConfigError("Use an explicit DEV/001 scale set and approved ado or gha provider.")
    for name in ("subscription_id", "tenant_id"):
        require_uuid(scale[name])
    network = scale["network"]
    if (not isinstance(network, dict) or set(network) != {"vnet_cidr", "max_projects"}
            or not isinstance(network["vnet_cidr"], str) or "${" in network["vnet_cidr"]
            or type(network["max_projects"]) is not int or not 1 <= network["max_projects"] <= 8):
        raise ConfigError("Supply the approved CIDR and integer network capacity; the API validates allocation.")
    return body


def check_target(target, request):
    if not isinstance(target, dict):
        raise FailureError("Create response has no target factory.")
    for field, expected in (
        ("kind", "ai"), ("key", request["factory_key"]),
        ("prefix", request["target_prefix"]), ("region", request["target_region"]),
        ("default_orchestrator", request["scale_sets"][0]["orchestrator"]),
        ("aifactory_version", request["aifactory_version"]),
    ):
        if target.get(field) != expected:
            raise FailureError(f"Create response changed the requested {field}; stop and inspect host state.")
    scales, projects = target.get("scale_sets"), target.get("projects")
    if not isinstance(scales, list) or not isinstance(projects, list):
        raise FailureError("Create response omitted scale sets or projects.")
    try:
        scale = exactly_one(scales, "new DEV/001 scale set")
        project = exactly_one(projects, "initial project001")
    except ValueError as error:
        raise FailureError(str(error)) from None
    if not isinstance(scale, dict) or not isinstance(project, dict):
        raise FailureError("Create response has malformed scale/project records.")
    for field, value in request["scale_sets"][0].items():
        actual = scale.get(field)
        if field == "network" and isinstance(actual, dict):
            actual = {key: actual.get(key) for key in value}
        if actual != value:
            raise FailureError(f"Create response changed scale-set {field}; stop and inspect host state.")
    factory_id, scale_id, project_id = (
        require_uuid(target.get("id")), require_uuid(scale.get("id")), require_uuid(project.get("id")),
    )
    if (project.get("number") != "001"
            or project.get("placements") != [{"environment": "dev", "scale_set_id": scale_id}]):
        raise FailureError("Expected exactly default project001 placed in the new DEV/001 scale set.")
    return {"factory_id": factory_id, "scale_set_id": scale_id, "project_id": project_id}


def check_create_preview(preview, request):
    validate_preview(preview)
    if (type(preview.get("contract_version")) is not int or preview["contract_version"] != 1
            or preview.get("operation_mode") != "configuration"):
        raise FailureError("Expected configuration-only catalog preview contract v1.")
    require_uuid(preview.get("confirmation_id"))
    return check_target(preview.get("target"), request)


def check_catalog(catalog):
    if (not isinstance(catalog, dict) or type(catalog.get("contract_version")) is not int
            or catalog["contract_version"] != 1 or catalog.get("mode") != "catalog"
            or not isinstance(catalog.get("factories"), list)
            or not isinstance(catalog.get("revision"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", catalog["revision"])):
        raise FailureError("Cannot verify the saved register. Inspect host state; never repeat confirmation.")


def prepare_factory(client, request, receipt_path):
    check_request(request)
    if Path(receipt_path).exists():
        raise ConfigError("Refusing to overwrite a review receipt; choose a new filename.")
    preview = client.catalog_prepare(request)
    # Blocked previews remain visible, but cannot produce a confirmable receipt.
    if isinstance(preview, dict) and (preview.get("can_execute") is False or preview.get("blockers")):
        return {"phase": "blocked", "preview": preview}, 3
    scope = check_create_preview(preview, request)
    write_receipt(str(receipt_path), client=client, purpose="catalog-confirm",
                  operation="factory-create", request_body=request, preview=preview)
    return {"phase": "configuration-preview", "request": request, "preview": preview,
            "receipt": str(receipt_path), **scope}, 0


def confirm_factory(client, receipt_path, *, approved=False):
    if not approved:
        raise ConfigError("Separate explicit approval (--confirm --yes) is required.")
    receipt = load_receipt(str(receipt_path), client=client, purpose="catalog-confirm",
                           operation_mode="configuration")
    if receipt["operation"] != "factory-create":
        raise ConfigError("Only a factory-create receipt may be confirmed by this example.")
    request = check_request(receipt["request"])
    expected_scope = check_create_preview(receipt["preview"], request)
    result = client.catalog_confirm(receipt["folder"], receipt["confirmation_id"])
    if (not isinstance(result, dict) or type(result.get("contract_version")) is not int
            or result["contract_version"] != 1 or result.get("job") is not None
            or not isinstance(result.get("catalog"), dict)):
        raise FailureError("Expected catalog-only confirmation, job:null. Inspect host state; never retry blindly.")
    check_catalog(result["catalog"])
    catalog = client.catalog_list(receipt["folder"])
    check_catalog(catalog)
    try:
        target = exactly_one(
            (item for item in catalog["factories"] if isinstance(item, dict)
             and item.get("id") == expected_scope["factory_id"]),
            "saved factory UUID",
        )
    except ValueError as error:
        raise FailureError(str(error)) from None
    actual_scope = check_target(target, request)
    if actual_scope != expected_scope:
        raise FailureError("Saved factory/project/scale UUIDs differ from the reviewed preview.")
    return {"phase": "configuration-saved", "folder": receipt["folder"],
            "catalog_revision": catalog["revision"], **actual_scope,
            "deployment_started": False, "publication_started": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, help="Rendered 01-create-factory.json; prepare only.")
    parser.add_argument("--receipt", type=Path, required=True, help="New receipt for prepare; reviewed receipt for confirm.")
    parser.add_argument("--confirm", action="store_true", help="Save only the separately approved configuration.")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.confirm:
            if args.request or not args.yes:
                raise ConfigError("Confirm requires --yes and the existing --receipt, without --request.")
            client = AzureFactoryClient()
            result = confirm_factory(client, args.receipt, approved=True)
            code = 0
        else:
            if not args.request or args.yes:
                raise ConfigError("Prepare requires --request and --receipt; --yes is confirm-only.")
            request = json.loads(args.request.read_text(encoding="utf-8-sig"))
            client = AzureFactoryClient()
            result, code = prepare_factory(client, request, args.receipt)
        print(json.dumps(redact_secrets(result, client.api_key), indent=2, allow_nan=False))
        return code
    except APIError as error:
        status = f" (HTTP {error.status})" if error.status is not None else ""
        print(f"Factory example stopped: {type(error).__name__}{status}. "
              "Inspect the approved host securely; do not blindly retry confirmation.", file=sys.stderr)
        return error.exit_code
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(f"Cannot read/use the request or receipt ({type(error).__name__}); "
              "no automatic retry is performed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
