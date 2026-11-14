#!/usr/bin/env python3
"""Opt-in Pipelines-only lifecycle coordination; never imports the Factory API.

The provider repository is the durable journal. Local files are only receipts
and review artifacts. A started stage is never replayed automatically: recovery
observes the existing native lifecycle claim and worker receipts.

Enrollment and Foundry identity-only phases require a freshly reviewed
continuation. They never report the requested common/project scenario complete.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4, uuid5


class PipelineError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise PipelineError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    try:
        require(str(UUID(value)) == value, "invalid-operation-id")
    except (ValueError, TypeError, AttributeError):
        raise PipelineError("invalid-operation-id") from None
    return value


def bound_plan(record):
    return {"operation_id": record["operation_id"], "snapshot_hash": record["snapshot_hash"],
            "plan": record["plan"], "prepared_at": record["prepared_at"]}


def verified_outcome(receipt):
    """Accept only terminal effects observed by an installed native adapter."""
    return isinstance(receipt, dict) and receipt.get("verified") is True and (
        receipt.get("status") == "succeeded" or receipt.get("status") == "continuation-required"
        and receipt.get("runtime_ready") is False
        and receipt.get("continuation", {}).get("requires_fresh_review") is True)


class LifecycleService:
    """One state machine, with separately testable authority/effect adapters."""

    def __init__(self, *, store, planner, executor, review, admission, configuration=None):
        self.store, self.planner, self.executor = store, planner, executor
        self.review, self.admission = review, admission
        self.configuration = configuration

    def _load(self, operation_id):
        revision, record = self.store.read(identifier(operation_id))
        require(isinstance(record, dict) and record.get("schema") == 1, "operation-not-found")
        require(record.get("operation_id") == operation_id, "operation-binding-mismatch")
        require(digest(record["snapshot"]) == record["snapshot_hash"], "snapshot-hash-mismatch")
        require(digest(bound_plan(record)) == record["plan_hash"], "plan-hash-mismatch")
        return revision, record

    def _save(self, revision, record):
        record["updated_at"] = now()
        return self.store.write(record["operation_id"], revision, record)

    def prepare(self, resolved, *, input_evidence=None, _continuation=None, _operation_id=None,
                _recovery=None, _residual=None):
        snapshot = copy.deepcopy(resolved)
        require(type(snapshot.get("request", {}).get("scenario")) is int
                and snapshot["request"]["scenario"] in range(1, 7), "unsupported-scenario")
        operation_id = _operation_id or str(uuid4())
        change = (self.configuration.prepare(snapshot)
                  if self.configuration is not None and _recovery is None else None)
        if _recovery is not None:
            plan = self.planner.prepare_recovery(snapshot, _recovery, operation_id,
                                                input_snapshot_hash=_continuation["input_snapshot_hash"])
            if self.configuration is not None:
                recover = getattr(self.configuration, "prepare_recovery", None)
                change = (recover(snapshot, _recovery, plan) if callable(recover)
                          else self.configuration.prepare(snapshot))
        elif _residual is not None:
            plan = self.planner.prepare_residual(snapshot, _residual, operation_id,
                                                input_snapshot_hash=_continuation["input_snapshot_hash"])
        else:
            plan = (self.planner.prepare(snapshot, operation_id, input_snapshot_hash=_continuation["input_snapshot_hash"])
                    if _continuation else self.planner.prepare(snapshot, operation_id))
        require(isinstance(plan, dict) and isinstance(plan.get("stages"), list) and plan["stages"],
                "nonempty-executable-plan-required")
        if change is not None:
            plan["configuration"] = change
        if _continuation is not None:
            plan.update(copy.deepcopy(_continuation))
        if input_evidence is not None:
            plan.setdefault("review", {})["input_artifact"] = copy.deepcopy(input_evidence)
        names = [stage.get("id") for stage in plan["stages"]]
        require(all(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]{1,64}", name) for name in names)
                and len(set(names)) == len(names), "unique-stage-identities-required")
        record = {"schema": 1, "operation_id": operation_id, "prepared_at": now(),
                  "status": "prepared", "snapshot": snapshot, "snapshot_hash": digest(snapshot),
                  "plan": copy.deepcopy(plan),
                  "stages": [{"id": name, "status": "pending"} for name in names]}
        record["plan_hash"] = digest(bound_plan(record))
        revision, existing = self.store.read(operation_id)
        require(existing is None, "operation-already-exists")
        self._save(revision, record)
        return record

    def prepare_recovery(self, operation_id, resolved, expected_plan_hash, *, input_evidence=None):
        from pipeline_lifecycle_recovery import input_hash
        _, prior = self._load(operation_id)
        require(expected_plan_hash == prior["plan_hash"], "reviewed-plan-hash-required")
        require(digest(resolved) == input_hash(prior), "snapshot-changed")
        require(prior["status"] in ("running", "cancel-pending", "reconciliation-required",
                                  "succeeded", "continuation-required"),
                "recovery-retained-operation-required")
        origin = self.review.origin(prior["snapshot"])
        recovery_id = str(uuid5(UUID(operation_id), digest(origin) + prior["plan_hash"] + ":recovery"))
        _, existing = self.store.read(recovery_id)
        if existing is not None:
            _, saved = self._load(recovery_id)
            require(saved["status"] == "prepared" and saved["plan"]["origin"] == origin
                    and saved["plan"].get("recovery_of") == {"operation_id": operation_id, "plan_hash": prior["plan_hash"]},
                    "recovery-operation-already-started")
            return saved
        return self.prepare(prior["snapshot"], input_evidence=input_evidence, _operation_id=recovery_id,
                            _recovery=prior, _continuation={
                                "recovery_of": {"operation_id": operation_id, "plan_hash": prior["plan_hash"]},
                                "input_snapshot_hash": input_hash(prior)})

    def prepare_continuation(self, operation_id, resolved, expected_plan_hash, *, input_evidence=None):
        from pipeline_lifecycle_recovery import continuation_snapshot, input_hash
        _, parent = self._load(operation_id)
        require(expected_plan_hash == parent["plan_hash"], "reviewed-plan-hash-required")
        snapshot = continuation_snapshot(parent, resolved)
        parent = self.observe(operation_id, release=False)
        require(parent["status"] == "continuation-required", "continuation-native-outcome-unverified")
        child_id = str(uuid5(UUID(operation_id), parent["plan_hash"] + ":continuation"))
        revision, parent = self._load(operation_id)
        require(parent.get("continuation_child", child_id) == child_id, "continuation-child-changed")
        if "continuation_child" not in parent:
            parent["continuation_child"] = child_id
            self._save(revision, parent)
        _, existing = self.store.read(child_id)
        if existing is None:
            child = self.prepare(snapshot, input_evidence=input_evidence, _operation_id=child_id,
                                 _residual=parent if parent["plan"]["stages"][0].get("kind") in (
                                     "retained-claim-reconciliation", "bootstrap-reconciliation") else None,
                                 _continuation={"continuation_of": {
                                     "operation_id": operation_id, "plan_hash": parent["plan_hash"]},
                                     "input_snapshot_hash": input_hash(parent)})
        else:
            _, child = self._load(child_id)
            require(child["plan"].get("continuation_of") == {
                "operation_id": operation_id, "plan_hash": parent["plan_hash"]}
                    and child["snapshot_hash"] == digest(snapshot)
                    and child["status"] == "prepared", "continuation-already-started")
            require(self.review.origin(snapshot) == child["plan"].get("origin"),
                    "continuation-provider-origin-changed")
        return child

    def execute(self, operation_id, resolved, expected_plan_hash):
        revision, record = self._load(operation_id)
        require(expected_plan_hash == record["plan_hash"], "reviewed-plan-hash-required")
        from pipeline_lifecycle_recovery import input_hash
        require(digest(resolved) == input_hash(record), "snapshot-changed")
        require(record["status"] == "prepared", "reconciliation-required")
        if record["plan"].get("continuation_of"):
            relationship = record["plan"]["continuation_of"]
            _, parent = self._load(relationship["operation_id"])
            require(parent["plan_hash"] == relationship["plan_hash"]
                    and parent.get("continuation_child") == operation_id
                    and parent["status"] == "continuation-required"
                    and parent.get("admission", {}).get("status") == "released"
                    and parent.get("finalization", {}).get("status") == "succeeded",
                    "continuation-parent-not-ready")
        # A hash selects the review; only the authenticated protected provider job
        # can supply approval. There is deliberately no approval JSON argument.
        record["approval"] = self.review.verify(record)
        claim = self.admission.acquire(record)
        require(isinstance(claim, dict), "durable-admission-claim-required")
        record["admission_claim"] = copy.deepcopy(claim)
        record["status"] = "running"
        revision = self._save(revision, record)
        if record["plan"].get("recovery_of"):
            relation = record["plan"]["recovery_of"]
            previous_revision, previous = self._load(relation["operation_id"])
            require(previous["plan_hash"] == relation["plan_hash"], "recovery-parent-binding-mismatch")
            previous["recovery_child"] = operation_id
            self._save(previous_revision, previous)
            revision, record = self._load(operation_id)
        for stage, checkpoint in zip(record["plan"]["stages"], record["stages"]):
            self.admission.assert_owned(record)
            checkpoint.update(status="running", started_at=now())
            revision = self._save(revision, record)
            try:
                receipt = self.executor.execute(stage, record)
                checkpoint["receipt"] = receipt
                require(receipt.get("verified") is True
                        and receipt.get("status") in ("succeeded", "continuation-required"),
                        "native-receipt-not-verified")
                checkpoint.update(status=receipt["status"], completed_at=now())
                revision = self._save(revision, record)
                if receipt["status"] == "continuation-required":
                    return self._finish(revision, record)
            except BaseException as error:
                checkpoint["status"] = "reconciliation-required"
                record["status"] = "reconciliation-required"
                record["error_code"] = getattr(error, "code", "stage-outcome-uncertain")
                # If this CAS itself is uncertain, leave the durable running
                # checkpoint untouched; a fresh process must observe it.
                self._save(revision, record)
                return record
        return self._finish(revision, record)

    def _finish(self, revision, record, *, release=True):
        complete = (all(row["status"] == "succeeded" for row in record["stages"])
                    and not record["plan"].get("continuation_required"))
        record["status"] = "succeeded" if complete else "continuation-required"
        record.pop("error_code", None)
        revision = self._save(revision, record)
        if self.configuration is not None:
            if "configuration" not in record:
                record["configuration"] = self.configuration.persist(record)
                revision = self._save(revision, record)
            require(isinstance(record["configuration"], dict)
                    and record["configuration"].get("revision") == digest(record["configuration"].get("document")),
                    "canonical-promotion-not-verified")
        # Never clear admission before the successful record is durable.
        if release:
            released = self.admission.release(record)
            if isinstance(released, dict):
                record["admission"] = released
                self._save(revision, record)
        return record

    def observe(self, operation_id, *, release=True):
        revision, record = self._load(operation_id)
        if record["status"] in ("prepared", "cancelled"):
            return record
        if record.get("completion"):
            child = self.observe(record["completion"]["operation_id"], release=False)
            require(child["plan_hash"] == record["completion"]["plan_hash"]
                    and child["plan"].get("continuation_of") == {
                        "operation_id": record["operation_id"], "plan_hash": record["plan_hash"]},
                    "continuation-completion-binding-mismatch")
            previous = record["status"]
            record["status"] = "succeeded" if child["status"] == "succeeded" else "reconciliation-required"
            if record["status"] != "succeeded":
                record["error_code"] = "continuation-outcome-unverified"
            if record["status"] != previous:
                self._save(revision, record)
            return record
        for stage, checkpoint in zip(record["plan"]["stages"], record["stages"]):
            if checkpoint["status"] == "pending":
                continue
            try:
                receipt = self.executor.observe(stage, record)
            except Exception as error:
                checkpoint["status"] = "reconciliation-required"
                if record["status"] != "cancel-pending":
                    record["status"] = "reconciliation-required"
                record["error_code"] = getattr(error, "code", "native-observation-unverified")
                self._save(revision, record)
                return record
            checkpoint["observation"] = receipt
            if receipt.get("verified") is True and receipt.get("status") in ("succeeded", "continuation-required"):
                checkpoint["status"] = receipt["status"]
            elif record["status"] != "cancel-pending":
                record["status"] = "reconciliation-required"
                checkpoint["status"] = "reconciliation-required"
        if all(stage["status"] in ("succeeded", "continuation-required") for stage in record["stages"]):
            return self._finish(revision, record, release=release)
        self._save(revision, record)
        return record

    def status(self, operation_id):
        """Read the durable operation without probing or mutating its outcome."""
        return self._load(operation_id)[1]

    def reconcile(self, operation_id):
        """Observe existing effects; never replay an uncertain write."""
        return self.observe(operation_id)

    def finalize(self, operation_id, resolved, expected_plan_hash):
        _, record = self._load(operation_id)
        require(expected_plan_hash == record["plan_hash"], "reviewed-plan-hash-required")
        from pipeline_lifecycle_recovery import input_hash
        require(digest(resolved) == input_hash(record), "snapshot-changed")
        proof = self.review.verify_finalizer(record)
        # Release may already have committed before the previous proof CAS was
        # acknowledged. Authenticate and reobserve, then let admission validate
        # the exact active claim OR its completed history; never reacquire it.
        observed = self.observe(operation_id, release=False)
        require(observed["status"] in ("succeeded", "continuation-required")
                and all(row["status"] in ("succeeded", "continuation-required") for row in observed["stages"]),
                "finalizer-native-outcome-unverified")
        released = self.admission.finalize(observed)
        require(isinstance(released, dict) and released.get("status") == "released",
                "admission-reconciliation-required")
        revision, record = self._load(operation_id)
        record["admission"] = released
        record["finalization"] = {"status": "succeeded", "proof": proof, "completed_at": now()}
        self._save(revision, record)
        if record["status"] == "succeeded":
            self._complete_parent(record)
        return record

    def _complete_parent(self, child):
        recovered = child["plan"].get("recovery_of")
        if recovered is not None:
            revision, prior = self._load(recovered["operation_id"])
            require(prior["plan_hash"] == recovered["plan_hash"]
                    and prior.get("recovery_child") == child["operation_id"], "recovery-parent-binding-mismatch")
            prior["recovery_completion"] = {"operation_id": child["operation_id"], "plan_hash": child["plan_hash"]}
            prior["status"] = "recovered"
            self._save(revision, prior)
            return
        relationship = child["plan"].get("continuation_of")
        if relationship is None:
            return
        revision, parent = self._load(relationship["operation_id"])
        require(parent["plan_hash"] == relationship["plan_hash"]
                and parent.get("continuation_child") == child["operation_id"]
                and parent.get("finalization", {}).get("status") == "succeeded"
                and parent.get("admission", {}).get("status") == "released",
                "continuation-parent-binding-mismatch")
        parent["completion"] = {"operation_id": child["operation_id"], "plan_hash": child["plan_hash"]}
        parent["status"] = "succeeded"
        self._save(revision, parent)
        self._complete_parent(parent)

    def cancel(self, operation_id):
        revision, record = self._load(operation_id)
        require(record["status"] not in ("succeeded", "cancelled"), "operation-already-terminal")
        if record["status"] == "prepared":
            record["status"] = "cancelled"
            self._save(revision, record)
            return record
        record["status"] = "cancel-pending"
        revision = self._save(revision, record)
        for stage, checkpoint in zip(record["plan"]["stages"], record["stages"]):
            if checkpoint["status"] in ("running", "reconciliation-required"):
                checkpoint["cancellation"] = self.executor.cancel(stage, record)
        self._save(revision, record)
        return record


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("prepare", "prepare-continuation", "prepare-recovery", "execute", "finalize", "status",
                                           "reconcile", "observe", "cancel", "capabilities"))
    result.add_argument("--request")
    result.add_argument("--repo-root", "--repository-root", dest="repo_root", default=".")
    result.add_argument("--source-root", default=str(Path(__file__).resolve().parents[2]))
    result.add_argument("--state-root")
    result.add_argument("--operation-id")
    result.add_argument("--expected-plan-hash")
    result.add_argument("--provider-context")
    result.add_argument("--output")
    return result


def verify_receipt(receipt, expected, *, service=None):
    """Read pipeline-finalized durable authority using provider GETs only."""
    require(isinstance(receipt, dict) and receipt.get("provider_context") == expected, "receipt-context-mismatch")
    operation_id = identifier(receipt.get("operation_id"))
    require(receipt.get("status") == "succeeded", "receipt-operation-not-succeeded")
    if service is None:
        from pipeline_dispatch import ProviderReceiptReader
        service = ProviderReceiptReader(expected)
    _, record = service._load(operation_id)
    require(record["plan_hash"] == receipt.get("plan_hash")
            and record["plan"].get("provider_context") == expected and record["status"] == "succeeded",
            "durable-receipt-binding-mismatch")
    require(record.get("admission", {}).get("status") == "released",
            "admission-reconciliation-required")
    finalization = record.get("finalization", {})
    proof = finalization.get("proof", {})
    require(finalization.get("status") == "succeeded" and proof.get("operation_id") == operation_id
            and proof.get("plan_hash") == record["plan_hash"]
            and proof.get("proof_kind") in ("github-rs256-native-finalizer", "ado-native-server-finalizer"),
            "pipeline-finalization-required")
    seen = {operation_id}
    parent = record
    while parent.get("completion"):
        completion = parent["completion"]
        child_id = identifier(completion.get("operation_id"))
        require(child_id not in seen and len(seen) < 8, "continuation-chain-invalid")
        seen.add(child_id)
        _, child = service._load(child_id)
        require(child["plan_hash"] == completion.get("plan_hash")
                and child["plan"].get("continuation_of") == {
                    "operation_id": parent["operation_id"], "plan_hash": parent["plan_hash"]}
                and child["status"] == "succeeded" and child.get("admission", {}).get("status") == "released",
                "continuation-completion-not-verified")
        child_proof = child.get("finalization", {}).get("proof", {})
        require(child.get("finalization", {}).get("status") == "succeeded"
                and child_proof.get("operation_id") == child_id and child_proof.get("plan_hash") == child["plan_hash"]
                and child_proof.get("proof_kind") in ("github-rs256-native-finalizer", "ado-native-server-finalizer"),
                "continuation-finalization-required")
        parent = child
    return {"outcome": "completed", "operation_id": operation_id, "plan_hash": record["plan_hash"]}


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "capabilities":
        print(json.dumps({"contract": "pipelines-only-lifecycle-v1", "scenarios": list(range(1, 7)),
                          "api_required": False, "durable_state": "provider-repository-cas",
                          "arm_parameter_transport": "arm-keyvault-reference-v1",
                          "automatic_uncertain_retry": False,
                          "acceptance": "production-adapters-offline-validated",
                          "continuation": "prepare-continuation-with-fresh-protected-review",
                          "unsupported": ["unreviewed-partial-write-replay", "mixed-provider-factory-cohorts"],
                          "requires": ["external-platform-bootstrap-or-native-enrollment", "shared-all-writer-admission",
                                       "native-provider-worker-dispatch-authority",
                                       "authenticated-pipeline-finalizer"]}))
        return 0
    try:
        require(args.request is not None, "request-file-required")
        import pipeline_inputs
        from pipeline_lifecycle_adapters import build_service
        request = pipeline_inputs.read_json(Path(args.repo_root), args.request)
        resolved = pipeline_inputs.resolve_request(Path(args.repo_root), request)
        context = (pipeline_inputs.read_json(Path(args.repo_root), args.provider_context)
                   if args.provider_context else None)
        if context is not None:
            require(isinstance(context, dict) and set(context) == {
                "request_path", "request_digest", "correlation_id", "consumer_commit", "source_commit",
                "provider", "run_id", "run_attempt", "scenario", "repository"},
                "provider-context-schema-invalid")
            require(context["request_digest"] == digest(resolved)
                    and context["source_commit"] == resolved["source"]["commit"]
                    and context["provider"] == resolved["request"]["provider"]
                    and context["scenario"] == resolved["request"]["scenario"],
                    "provider-context-binding-mismatch")
        service = build_service(resolved, repo_root=Path(args.repo_root),
                                source_root=Path(args.source_root),
                                state_root=Path(args.state_root) if args.state_root else
                                Path(args.repo_root) / ".pipeline-lifecycle", provider_context=context)
        if args.command in ("prepare", "prepare-continuation", "prepare-recovery"):
            from pipeline_dispatch import input_evidence
            evidence = input_evidence(Path(args.repo_root), args.request)
            if args.command in ("prepare-continuation", "prepare-recovery"):
                require(args.operation_id is not None, "operation-id-required")
                action = getattr(service, args.command.replace("-", "_"))
                record = action(args.operation_id, resolved, args.expected_plan_hash, input_evidence=evidence)
            else:
                record = (service.prepare(resolved, input_evidence=evidence) if evidence is not None
                          else service.prepare(resolved))
        else:
            require(args.operation_id is not None, "operation-id-required")
            record = (getattr(service, args.command)(args.operation_id, resolved, args.expected_plan_hash)
                      if args.command in ("execute", "finalize") else getattr(service, args.command)(args.operation_id))
        # Never print the full configuration or native parameter payload.
        result = {key: record[key] for key in ("operation_id", "plan_hash", "status")}
        result["review"] = record["plan"].get("review", {})
        result["provider_context"] = record["plan"].get("provider_context")
        result["authority"] = {
            "target": {key: record["snapshot"]["scales"][0][key] for key in ("tenant_id", "subscription_id")},
            "ado_tenant_id": (record["snapshot"].get("binding", {}).get("bootstrap", {}).get("ado_tenant_id")
                              or record["snapshot"]["configuration"].get("factory", {}).get("ado_tenant_id"))}
        result["admission"] = record.get("admission")
        result["finalization"] = record.get("finalization")
        if record["status"] == "continuation-required":
            result["continuation"] = {"command": "prepare-continuation", "requires_fresh_review": True,
                                      "operation_id": record["operation_id"], "plan_hash": record["plan_hash"]}
        if record.get("completion"):
            result["completion"] = record["completion"]
        result["stages"] = [{"id": row["id"], "status": row["status"]} for row in record["stages"]]
        if "error_code" in record:
            result["error_code"] = record["error_code"]
        text = json.dumps(result, indent=2)
        if args.output:
            path = Path(args.output)
            require(not path.exists() and not path.is_symlink(), "new-review-output-required")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(text + "\n")
        print(text)
        expected_status = {"prepare": "prepared", "prepare-continuation": "prepared", "prepare-recovery": "prepared",
                           "cancel": "cancelled"}.get(
            args.command, "succeeded")
        if record["status"] == "continuation-required" and args.command in ("execute", "finalize"):
            return 3
        return 0 if record["status"] == expected_status else 2
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error_code": getattr(error, "code", "pipeline-input-invalid")}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
