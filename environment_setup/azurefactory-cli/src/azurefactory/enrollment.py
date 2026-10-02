"""Local enrollment reviews around the bundled, canonical stdlib core."""

from contextlib import contextmanager
from functools import lru_cache
import importlib
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace

from .client import redact_secrets
from .errors import APIError, BlockedError, ConfigError, FailureError
from .review import load_receipt, validate_preview, write_receipt


PLAN_FORMAT = "azurefactory-enrollment-plan-v1"
RESULT_FORMAT = "azurefactory-enrollment-result-v1"
BLOB_OPTIONS = {"coordination_storage_mode", "coordination_account_creation", "coordination_account_id",
                "coordination_resource_group_id", "container", "coordination_blob", "public_network_access"}


@lru_cache(maxsize=1)
def core():
    name = "azurefactory._vendor.factory_enrollment"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
    package = Path(__file__).resolve().parents[2]
    if package.name != "azurefactory-cli" or package.parent.name not in ("environment_setup", "aifactory-templates"):
        raise ConfigError("Enrollment core is missing; reinstall a complete CLI distribution.")
    root = package.parent.parent
    for path in (root / "bootstrap" / "lib" / "factory_enrollment.py",
                 root / "azure-enterprise-scale-ml" / "bootstrap" / "lib" / "factory_enrollment.py",
                 root / "lib" / "factory_enrollment.py"):
        if path.is_file():
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise ConfigError("Canonical enrollment source is missing; install a complete CLI distribution.")


@contextmanager
def guarded():
    implementation = core()
    try:
        yield implementation
    except implementation.EnrollmentError as exc:
        code = exc.code
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9-]{1,120}", code):
            code = "enrollment-failed"
        blocked = any(word in code for word in ("changed", "blocked", "reconciliation", "conflict"))
        raise (BlockedError if blocked else ConfigError)(code) from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise ConfigError("Invalid enrollment input or unavailable file; inspect state before retrying.") from None


def read_document(path):
    with Path(path).open("rb") as handle:
        value = core().parse_json(handle.read(core().MAX_BYTES + 1))
    if redact_secrets(value, None) != value:
        raise ConfigError("Enrollment documents must not contain secret fields or credentials.")
    return value


def available(path):
    if path and (Path(path).exists() or Path(path).is_symlink()):
        raise ConfigError("Refusing to overwrite an existing enrollment artifact.")
    if path and not Path(path).parent.is_dir():
        raise ConfigError("Enrollment artifact parent directory must already exist.")


def write_document(path, value):
    if redact_secrets(value, None) != value:
        raise ConfigError("Refusing to persist sensitive enrollment content.")
    raw = core().canonical(value)
    core().require(len(raw) <= core().MAX_BYTES, "document-too-large")
    with Path(path).open("xb") as handle:
        handle.write(raw + b"\n")


def seal(value):
    return {**value, "artifact_hash": core().digest(value)}


def plan_artifact(request, review):
    return seal({"format": PLAN_FORMAT, "schema": 1, "consumer_root": request["consumer_root"],
                 "reference_hash": request["consumer_hash"], "request_hash": core().digest(request),
                 "request": request, "review": review})


def validate_artifact(value, format_name):
    implementation = core()
    expected = ({"format", "schema", "consumer_root", "reference_hash", "request_hash", "request", "review", "artifact_hash"}
                if format_name == PLAN_FORMAT else {"format", "schema", "plan", "result", "artifact_hash"})
    implementation.require(isinstance(value, dict) and set(value) == expected
                           and value["format"] == format_name and type(value["schema"]) is int
                           and value["schema"] == 1, "invalid-enrollment-artifact")
    implementation.require(value["artifact_hash"] == implementation.digest(
        {k: v for k, v in value.items() if k != "artifact_hash"}), "enrollment-artifact-changed")
    if format_name == RESULT_FORMAT:
        return validate_artifact(value["plan"], PLAN_FORMAT)
    request, review = value["request"], value["review"]
    implementation.require(isinstance(request, dict) and isinstance(review, dict), "invalid-enrollment-artifact")
    implementation.require(value["request_hash"] == implementation.digest(request)
                           and review["scope_hash"] == value["request_hash"]
                           and value["consumer_root"] == request["consumer_root"]
                           and value["reference_hash"] == request["consumer_hash"], "enrollment-request-changed")
    implementation.require(review["plan_hash"] == implementation.digest(
        {k: v for k, v in review.items() if k != "plan_hash"}), "enrollment-review-changed")
    implementation.require(review["target"] == request["target"] and review["route"] == request["route"]
                           and type(review["acknowledge_exclusive_writer_governance"]) is bool,
                           "enrollment-review-scope-mismatch")
    target = request["target"]
    fresh = implementation.load_request(request["consumer_root"], target["factory_id"], target["scaleset_id"],
                                        target["environment"], request["options"])
    implementation.require(fresh == request, "consumer-or-request-changed")
    return request, review


def request_from_args(args):
    required = ("consumer_root", "factory_id", "scale_set_id", "environment", "options")
    if any(not getattr(args, field, None) for field in required):
        raise ConfigError("Explicit --consumer-root, --factory-id, --scale-set-id, --environment and --options are required.")
    return core().load_request(args.consumer_root, args.factory_id, args.scale_set_id, args.environment,
                               read_document(args.options))


def check_selection(args, request):
    selected = {"consumer_root": request["consumer_root"], "factory_id": request["target"]["factory_id"],
                "scale_set_id": request["target"]["scaleset_id"], "environment": request["target"]["environment"]}
    for field, expected in selected.items():
        supplied = getattr(args, field, None)
        if field == "consumer_root" and supplied:
            supplied = str(Path(supplied).resolve())
        if supplied is not None and supplied != expected:
            raise ConfigError("Explicit enrollment selection conflicts with the saved plan.")
    if args.options and read_document(args.options) != request["options"]:
        raise ConfigError("Enrollment options differ from the saved review.")
    if args.expected_orchestrator and args.expected_orchestrator != request["route"]["kind"]:
        raise ConfigError("orchestrator-mismatch")


def plan(args):
    with guarded() as implementation:
        available(args.save_plan)
        request = request_from_args(args)
        check_selection(args, request)
        review = implementation.plan(
            request, acknowledge_exclusive_writer_governance=args.acknowledge_exclusive_writer_governance)
        if args.save_plan:
            write_document(args.save_plan, plan_artifact(request, review))
        return review


def ensure(args):
    with guarded() as implementation:
        if not args.yes:
            raise ConfigError("Enrollment ensure requires --yes after a separate review.")
        available(args.save_result)
        if args.plan:
            artifact = read_document(args.plan)
            request, review = validate_artifact(artifact, PLAN_FORMAT)
            if args.expected_plan is not None and args.expected_plan != review["plan_hash"]:
                raise ConfigError("--expected-plan conflicts with the saved plan.")
            if args.acknowledge_exclusive_writer_governance != review["acknowledge_exclusive_writer_governance"]:
                raise ConfigError("Governance acknowledgment differs from the saved plan; review again.")
            expected = review["plan_hash"]
        else:
            request = request_from_args(args)
            expected = args.expected_plan
            if not expected:
                raise ConfigError("Enrollment ensure requires --plan or --expected-plan from a separate review.")
            if args.save_result:
                raise ConfigError("--save-result requires --plan so the reviewed scope is preserved for publication.")
        check_selection(args, request)
        result = implementation.ensure(request, expected, yes=True,
                                       acknowledge_exclusive_writer_governance=args.acknowledge_exclusive_writer_governance)
        if args.save_result:
            try:
                write_document(args.save_result, seal({"format": RESULT_FORMAT, "schema": 1,
                                                       "plan": artifact, "result": result}))
            except (OSError, ValueError, TypeError, APIError, implementation.EnrollmentError):
                raise FailureError("Enrollment result could not be saved; resources may have changed. "
                                   "Inspect state before retrying; no rollback was attempted.") from None
        return result


def binding_request(result_path, expected_revision):
    """Reconstruct the exact candidate with core logic; never infer or write a binding."""
    with guarded() as implementation:
        implementation.require(isinstance(expected_revision, str)
                               and re.fullmatch(r"[a-f0-9]{64}", expected_revision), "catalog-revision-required")
        artifact = read_document(result_path)
        request, review = validate_artifact(artifact, RESULT_FORMAT)
        result = artifact["result"]
        implementation.require(isinstance(result, dict) and result.get("enrollment_complete") is True
                               and result.get("status") in ("changed", "unchanged")
                               and result.get("publication_required") is True and result.get("runtime_ready") is False
                               and review["acknowledge_exclusive_writer_governance"] is True,
                               "complete-enrollment-result-required")
        binding, identity = result["binding_candidate"], result["identity"]
        implementation.require(isinstance(binding, dict) and isinstance(identity, dict), "binding-candidate-required")
        implementation._validate_binding(binding)
        checked_identity = implementation._identity(
            {"id": identity["id"], "tenantId": identity["tenant_id"],
             "clientId": identity["client_id"], "principalId": identity["principal_id"]}, request)
        implementation.require(checked_identity == identity, "enrollment-identity-changed")
        # The ensure result carries the coordination digest, not the full live document.
        # Keep that reviewed digest; runtime independently verifies it against live storage.
        expected = implementation.binding_candidate(request, identity, {"revision": binding["locks"]["revision"]})
        expected["locks"]["coordination_hash"] = binding["locks"]["coordination_hash"]
        implementation.require(expected == binding, "binding-candidate-scope-mismatch")
        return {"folder": str(Path(request["consumer_root"]) / "azurefactory"), "contract_version": 1,
                "action": "configure-binding", "factory_id": request["target"]["factory_id"],
                "expected_revision": expected_revision, "binding": binding}


def convenience_request(args):
    """Apply opt-in convenience defaults without changing low-level callers."""
    implementation = core()
    options = read_document(args.options)
    implementation.require(isinstance(options, dict), "invalid-enrollment-options")
    document = read_document(Path(args.consumer_root) / "azurefactory" / "register.json")
    if "coordination_mode" not in options:
        binding = document.get("bindings", {}).get(args.factory_id, {}).get(args.expected_orchestrator)
        if binding is None:
            factory = implementation._one(document.get("factories"), "id", implementation.guid(args.factory_id),
                                         "exact-registered-factory-required")
            scale = implementation._one(factory.get("scale_sets"), "id", implementation.guid(args.scale_set_id),
                                       "exact-registered-scaleset-required")
            binding = document.get("bindings", {}).get(factory["id"], {}).get(scale.get("orchestrator"))
        mode = (binding["locks"].get("coordination_mode", "blob") if binding else
                "blob" if BLOB_OPTIONS.intersection(options) else "single-writer")
        options = {**options, "coordination_mode": mode}
    request = implementation.load_request(args.consumer_root, args.factory_id, args.scale_set_id,
                                         args.environment, options)
    if args.expected_orchestrator and args.expected_orchestrator != request["route"]["kind"]:
        raise ConfigError("orchestrator-mismatch")
    if "create_resource_group_ids" not in options:
        selected = request["target"]
        shared = set(request["common_dependencies"])
        for entry in request["existing_bindings"]:
            for target in entry["binding"]["targets"]:
                shared.update(implementation.rg_id(x) for x in target.get("common_dependency_ids", []))
                if entry["factory_id"] != selected["factory_id"] or target["scale_set_id"] != selected["scaleset_id"]:
                   shared.update(implementation.rg_id(x) for x in target["resource_group_ids"])
        # Exact writable selections declare the new owner; live ownership checks
        # still reject every existing unowned/conflicting group before any writes.
        creation = set(request["scopes"]) - shared
        identity_group = request["identity_id"].split("/providers/")[0]
        if (not request["reuse_identity"] and options.get("identity_resource_group_id")
                and identity_group not in shared
                and identity_group != request.get("account_id", "").split("/providers/")[0]):
            creation.add(identity_group)
        if creation:
            options = {**options, "create_resource_group_ids": sorted(creation),
                      "approved_group_creation_scope": "/subscriptions/" + selected["subscription_id"]}
            request = implementation.load_request(args.consumer_root, args.factory_id, args.scale_set_id,
                                                 args.environment, options)
    implementation.require(document == read_document(Path(args.consumer_root) / "azurefactory" / "register.json"),
                           "consumer-or-request-changed")
    validate_registered_intent(document, request)
    return request


def validate_registered_intent(document, request):
    """Reject known catalog publication conflicts before creating Azure resources."""
    implementation = core()
    selected = request["target"]
    settings = document["configurations"][selected["factory_id"]]["factory"]
    implementation.require(isinstance(settings, dict), "registered-factory-settings-required")
    saved_mode = settings.get("coordination_mode", "blob")
    implementation.require(saved_mode in ("blob", "single-writer"), "invalid-saved-coordination-mode")
    implementation.require(saved_mode == request.get("coordination_mode", "blob"),
                           "saved-coordination-mode-conflict-configure-through-api-first")
    writable = set(request["scopes"]) | set(request["create_resource_group_ids"])
    if not request["reuse_identity"]:
        writable.add(request["identity_id"].split("/providers/")[0])
    for factory in document["factories"]:
        for scale in factory["scale_sets"]:
            if factory["id"] == selected["factory_id"] and scale["id"] == selected["scaleset_id"]:
                continue
            owned = scale.get("owned_resource_ids", [])
            implementation.require(isinstance(owned, list) and all(isinstance(item, str) for item in owned),
                                   "invalid-registered-owned-resources")
            groups = {implementation.rg_id("/".join(item.split("/")[:5])) for item in owned}
            implementation.require(not groups.intersection(writable), "registered-resource-group-owner-conflict")


def cost_preview(request):
    """An offline, explicitly unpriced preview of what enrollment actually creates."""
    single = request.get("coordination_mode") == "single-writer"
    services = [
        {"service": "Resource groups and managed identity federation", "enabled": True,
         "region": request["target"]["region"], "sku": None,
         "resource_group_ids": request["create_resource_group_ids"], "identity_id": request["identity_id"],
         "drivers": ["Management-plane prerequisites only; workload resources are not deployed by enrollment."]},
        {"service": "Coordination Blob storage", "enabled": not single,
         "region": request["target"]["region"] if not single else None,
         "sku": ((request.get("coordination_account_creation") or {}).get("sku", {}).get("name")
                or ("Standard_LRS" if not single and request.get("coordination_storage_mode") == "dedicated"
                    else None)),
         "sku_basis": "Requested new account only; an existing account is reused unchanged.",
         "drivers": [] if single else ["Stored GB, transactions, redundancy, transfer and private networking."],
         "pricing_url": "https://azure.microsoft.com/pricing/details/storage/blobs/"},
        {"service": "GitHub Actions" if request["route"]["kind"] == "gha" else "Azure Pipelines",
         "enabled": True, "runner": request["route"]["runner"], "sku": None,
         "drivers": ["Plan allowances, execution minutes; self-hosted compute/networking are provisioned separately.",
                    "Private provider Git state is used; no coordination storage or Blob data RBAC." if single
                    else "Blob leases coordinate writers."],
         "pricing_url": ("https://docs.github.com/billing/managing-billing-for-your-products/managing-billing-for-github-actions"
                        if request["route"]["kind"] == "gha" else
                        "https://azure.microsoft.com/pricing/details/devops/azure-devops-services/")},
    ]
    return {"format": "azurefactory-enrollment-cost-preview-v1", "informational": True, "status": "unpriced",
            "region": request["target"]["region"], "request_hash": core().digest(request),
            "estimated_total": None, "services": services,
            "limitations": ["No retail pricing service is required or contacted; this is not a dollar estimate.",
                           "Existing resource SKUs/regions and usage are not inferred from creation defaults.",
                           "Full workload services/SKUs, AI tokens, capacity, discounts, taxes and shared costs are not "
                           "known from enrollment options and are excluded. Review the effective deployment parameters "
                           "before the separately approved runtime deployment."],
            "pricing_url": "https://azure.microsoft.com/pricing/calculator/"}


def plan_and_publish(args, api, report):
    """One bounded consent; unchanged plan/ensure and receipt validation contracts."""
    with guarded():
        folder = Path(args.artifact_dir).resolve()
        if folder.exists() or folder.is_symlink() or not folder.parent.is_dir():
            raise ConfigError("--artifact-dir must be a new directory with an existing parent.")
        request = convenience_request(args)
        folder.mkdir()
        paths = {name: str(folder / filename) for name, filename in (
            ("options", "options.json"), ("plan", "plan.json"), ("result", "result.json"),
            ("cost", "cost-preview.json"), ("receipt", "binding.receipt.json"),
            ("ensure_intent", "ensure-intent.json"),
            ("intent", "publication-intent.json"), ("publication", "publication.json"),
            ("outcome", "outcome.json"))}
        phase, writes_attempted, publication_attempted = "plan", False, False

        def finish(status, **fields):
            outcome = {"status": status, "phase": phase, "published": False, "runtime_ready": False,
                      "artifacts": paths, "reconciliation_required": False, **fields}
            write_document(paths["outcome"], seal(outcome))
            return outcome

        try:
            write_document(paths["options"], request["options"])
            preview = cost_preview(request)
            write_document(paths["cost"], preview)
            report({"cost_preview": preview, "approval_scope": {
                "target": request["target"], "create_resource_group_ids": request["create_resource_group_ids"],
                "identity_id": request["identity_id"], "deployment_roles": request["deployment_roles"],
                "coordination_mode": request.get("coordination_mode", "blob"),
                "note": "--yes approves only this bounded request, never subscription-wide role grants."}})
            local = SimpleNamespace(**vars(args))
            local.options, local.save_plan = paths["options"], paths["plan"]
            review = plan(local)
            reviewed_request, _ = validate_artifact(read_document(paths["plan"]), PLAN_FORMAT)
            core().require(reviewed_request == request, "consumer-or-request-changed")
            report({"enrollment_plan": review})
            if review.get("can_ensure") is not True or review.get("blockers"):
                return finish("blocked", blockers=review.get("blockers", []))
            if not args.yes:
                return finish("approval-required")
            phase = "catalog-preflight"
            catalog_folder = str(Path(request["consumer_root"]) / "azurefactory")
            catalog = api.catalog_list(catalog_folder)
            revision = catalog.get("revision")
            core().require(isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{64}", revision),
                          "catalog-revision-required")
            core().require(not args.expected_revision or args.expected_revision == revision,
                          "catalog-revision-changed")
            phase = "ensure"
            write_document(paths["ensure_intent"], seal({
                "status": "enrollment-pending-or-uncertain", "plan_hash": review["plan_hash"],
                "expected_catalog_revision": revision,
                "note": "If result.json is absent, inspect live/provider state before retrying. No automatic retry."}))
            writes_attempted = True
            local.plan, local.save_result, local.expected_plan = paths["plan"], paths["result"], review["plan_hash"]
            result = ensure(local)
            if (result.get("enrollment_complete") is not True or result.get("blockers")
                   or result.get("reconciliation_required")):
                return finish("blocked", result=result,
                             reconciliation_required=bool(result.get("changed") or result.get("reconciliation_required")))
            phase = "prepare-binding"
            body = binding_request(paths["result"], revision)
            prepared = api.catalog_prepare(body)
            write_receipt(paths["receipt"], client=api, purpose="catalog-confirm", operation="enrollment-binding",
                         request_body=body, preview=prepared)
            if prepared.get("can_execute") is not True or prepared.get("blockers"):
                return finish("blocked", blockers=prepared.get("blockers", []), enrollment_complete=True)
            validate_preview(prepared)
            receipt = load_receipt(paths["receipt"], client=api, purpose="catalog-confirm", operation_mode="configuration")
            core().require(receipt["operation"] == "enrollment-binding" and receipt["request"] == body,
                          "enrollment-publication-receipt-changed")
            phase = "publish"
            write_document(paths["intent"], seal({
                "status": "publication-pending-or-uncertain", "receipt_hash": core().digest(receipt),
                "confirmation_id": receipt["confirmation_id"],
                "note": "If publication.json is absent, inspect the API catalog before retrying. No automatic retry."}))
            publication_attempted = True
            published = api.catalog_confirm(receipt["folder"], receipt["confirmation_id"])
            write_document(paths["publication"], published)
            if (type(published.get("contract_version")) is not int or published["contract_version"] != 1
                   or not isinstance(published.get("catalog"), dict) or published.get("job") is not None):
                raise FailureError("Invalid publication response; inspect the catalog before retrying.")
            return finish("published", published=True, enrollment_complete=True)
        except (APIError, core().EnrollmentError, OSError, ValueError, KeyError, TypeError, AttributeError,
                RecursionError, KeyboardInterrupt) as exc:
            # Persist conservative uncertainty even if the response was lost. Never
            # retry a mutation or erase the core/provider's pending claim.
            code = exc.code if isinstance(exc, core().EnrollmentError) else getattr(exc, "message", "")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9-]{1,120}", code):
                code = "enrollment-or-publication-failed"
            try:
                finish("failed", reconciliation_required=writes_attempted,
                      publication_uncertain=publication_attempted, error=code)
            except (APIError, core().EnrollmentError, OSError):
                raise FailureError("Could not persist enrollment outcome; inspect intent files and live state before retrying.") from None
            if writes_attempted:
                raise FailureError("Enrollment/publication stopped; inspect saved artifacts and live state before retrying. "
                                  "No rollback or automatic mutation retry was attempted.") from None
            raise
