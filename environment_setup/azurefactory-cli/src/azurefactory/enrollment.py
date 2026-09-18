"""Local enrollment reviews around the bundled, canonical stdlib core."""

from contextlib import contextmanager
from functools import lru_cache
import importlib
import importlib.util
from pathlib import Path
import re

from .client import redact_secrets
from .errors import APIError, BlockedError, ConfigError, FailureError


PLAN_FORMAT = "azurefactory-enrollment-plan-v1"
RESULT_FORMAT = "azurefactory-enrollment-result-v1"


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
