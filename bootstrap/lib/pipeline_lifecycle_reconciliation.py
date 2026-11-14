"""Pipeline-owned, reviewed reconciliation of one retained native claim.

No Azure write, dispatch, retry, receipt completion or configuration promotion is
performed. One provider CAS replaces the retained outer claim, releases the
*exact* stopped native claim and adds an audit, preserving receipts and ownership.
An interrupted receipt remains interrupted; provider termination is not success.

Install ``NativeReconciliationEvidence(review, cloud_factory=...)`` as ``evidence``;
request JSON cannot select an authority adapter. ``prepare(snapshot, prior_record,
new_operation_id)`` returns a standalone stage. ``acquire(record)`` authenticates
the NEW protected review and returns the atomically installed replacement outer
claim. ``execute`` and ``observe`` are read-only durable-result verification.
``prepare_residual(snapshot, reconciliation_record, new_operation_id, planner=...)``
performs a fresh native prepare only after reconciliation and outer finalization.
Its returned plan still needs its own protected review and new admission claim.
Live IDs, principals, ownership, references, permissions and quiescence establish
safety; fingerprint/etag/time and canonical generation drift only warn.
When the inner claim is already absent, only exact succeeded receipts and fresh
expected-effect verification permit outer-only recovery. ``completed_outcome``
then supplies native children for the caller's canonical finalization; it never
promotes configuration here. ``requires_reprepare`` is false except for a proven
Foundry identity-only outcome. Previously released outer history is preserved.
Full Foundry runtime completion remains blocked pending live agent/grant proof.
"""

import copy
import fnmatch
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID, uuid5

import factory_lifecycle as fl
import lifecycle_admission
import provider_repository_state
from pipeline_lifecycle import bound_plan, canonical as canonical_json, digest, identifier, now, require


CONTRACT = "pipeline-retained-claim-reconciliation-v1"
AUDIT_PREFIX = "pipeline-claim-reconciliations/"
KIND = "retained-claim-reconciliation"
TERMINAL_RECEIPTS = {"succeeded", "blocked", "reconciliation-required"}
INTERRUPTED_RECEIPTS = {"running", "claimed"}
DIAGNOSTICS = {"body_hash", "etag", "observed_at", "checked_at", "updated_at", "observed_time", "diagnostic_drift",
               "inventory_hash", "closure_hash", "owner_hash", "identity_hash", "permission_hash", "dependency_hash"}


def _semantic_document(document):
    return {key: value for key, value in document.items() if key != "generation"}


def _evidence_semantics(value):
    """Compare actual authority/inventory facts, never observation fingerprints."""
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in DIAGNOSTICS or key == "metadata":
                continue
            if key == "closure":
                child = {
                    "groups": sorted(child.get("groups", {})), "resources": sorted(child.get("resources", {})),
                    "collections": {path: {field: row[field] for field in ("ids", "unsupported", "not_applicable")
                                           if field in row} for path, row in child.get("collections", {}).items()},
                    "references": child.get("references", {}),
                    "inline": child.get("inline", {}),
                }
            result[key] = _evidence_semantics(child)
        return result
    if isinstance(value, list):
        return sorted((_evidence_semantics(child) for child in value), key=canonical_json)
    return value


def _evidence_warnings(observed, reviewed):
    if observed == reviewed:
        return []
    return ["reconciliation-evidence-diagnostic-drift"] if (
        _evidence_semantics(observed) == _evidence_semantics(reviewed)
    ) else ["reconciliation-live-evidence-drift-new-review-required"]


def _not_found(body, expected, code):
    error = body.get("error") if isinstance(body, dict) else None
    require(isinstance(error, dict) and error.get("code") in expected, code)


def _journal_key(operation_id):
    return "pipeline-lifecycle/" + identifier(operation_id) + ".json"


def _integrity(record):
    require(isinstance(record, dict) and record.get("schema") == 1
            and digest(record.get("snapshot")) == record.get("snapshot_hash")
            and digest(bound_plan(record)) == record.get("plan_hash"),
            "reconciliation-operation-integrity-required")


def _scope_set(documents):
    return sorted({scope.lower() for document in documents
                   for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]})


def _remote(document):
    return "deployment" in document or document.get("deletion", {}).get(
        "inventory_mode") == "ordered-project-pipelines-v1"


class RetainedClaimReconciliation:
    def __init__(self, provider, *, review, admission, evidence):
        require(callable(getattr(provider, "read", None)) and callable(getattr(provider, "replace", None))
                and callable(getattr(review, "verify", None)) and callable(getattr(review, "origin", None))
                and callable(getattr(admission, "assert_owned", None)) and callable(evidence),
                "reconciliation-installed-adapters-required")
        self.provider, self.review, self.admission, self.evidence = provider, review, admission, evidence
        self.attempted_operations = set()

    def _state(self, factory_id):
        head, state = self.provider.read()
        require(head is not None and isinstance(state, dict) and isinstance(state.get("records"), dict)
                and state.get("repository") == self.provider.route["repository"],
                "reconciliation-provider-state-required")
        outer = state["records"].get(lifecycle_admission.RECORD)
        require(isinstance(outer, dict) and outer.get("schema") == 1
                and outer.get("policy", {}).get("repository") == state["repository"],
                "reconciliation-outer-admission-required")
        policy = outer["policy"].get("factories", {}).get(factory_id, {})
        require(policy.get("all_writers") == lifecycle_admission.PROTOCOL
                and policy.get("shared_scopes") == []
                and set(policy.get("operations", [])) == lifecycle_admission.OPERATIONS
                and set(policy.get("routes", [])) == {"api", "pipeline"},
                "reconciliation-all-writer-policy-required")
        canonical = outer.get("canonical", {}).get(factory_id)
        require(isinstance(canonical, dict) and isinstance(canonical.get("document"), dict)
                and canonical.get("revision") == digest(canonical["document"])
                and all(value == canonical for value in outer["canonical"].values()),
                "reconciliation-canonical-invalid")
        return head, state, outer, canonical

    @staticmethod
    def _prior(state, prior_id, snapshot):
        prior = state["records"].get(_journal_key(prior_id))
        require(isinstance(prior, dict), "reconciliation-durable-prior-operation-required")
        _integrity(prior)
        require(prior.get("operation_id") == prior_id and prior.get("snapshot") == snapshot
                and (prior.get("status") in ("running", "cancel-pending", "reconciliation-required")
                     or state.get("active") is None
                     and prior.get("status") in ("succeeded", "continuation-required")),
                "reconciliation-prior-operation-changed")
        stages = [stage for stage in prior["plan"]["stages"] if stage.get("kind") == "lifecycle"]
        require(len(stages) == 1 and stages[0].get("manifests"),
                "reconciliation-exact-native-stage-required")
        return prior, stages[0]["manifests"]

    @staticmethod
    def _native(state, documents):
        """Bind immutable claims and receipts, including every member of a cohort."""
        active = state.get("active")
        completed = active is None
        require(completed or isinstance(active, dict) and active.get("kind") in ("run", "deletion-cohort"),
                "reconciliation-exact-native-claim-required")
        require(len({document["run_id"] for document in documents}) == len(documents)
                and len({document["manifest_hash"] for document in documents}) == len(documents),
                "reconciliation-duplicate-native-manifest")
        scopes = _scope_set(documents)
        context = active.get("context") if not completed else None
        require(completed or isinstance(context, dict) and context and len(set(context.values())) == 1
                and all(fl.guid(value) for value in context.values()),
                "reconciliation-native-context-invalid")
        records = state["records"]
        selected = {}
        cohort = all(document["operation"] == "delete" for document in documents) if completed else (
            active["kind"] == "deletion-cohort")
        if not cohort:
            require(len(documents) == 1 and (completed or active.get("run_id") == documents[0]["run_id"]
                    and active.get("manifest_hash") == documents[0]["manifest_hash"]
                    and set(context) == set(scopes)), "reconciliation-native-claim-mismatch")
        else:
            hashes = sorted(document["manifest_hash"] for document in documents)
            logical = {"factory/" + document["target"]["factory_id"] for document in documents}
            logical.update("scaleset/" + document["target"]["factory_id"] + "/"
                           + document["target"]["scaleset_id"] for document in documents)
            require(all(document["operation"] == "delete" for document in documents)
                    and (completed or active.get("manifests") == hashes and active.get("cohort_hash") == fl.digest(hashes)
                    and set(context) == set(scopes) | logical and active.get("claim_id") in context.values()
                    and active.get("owner_hash") == fl.digest({
                        key: value for key, value in active.items() if key != "owner_hash"})),
                    "reconciliation-exact-cohort-required")
            cohort_hash = fl.digest(hashes)
            key = "cohorts/" + cohort_hash + ".json"
            aggregate = records.get(key)
            require(isinstance(aggregate, dict) and aggregate.get("cohort_hash") == cohort_hash
                    and aggregate.get("factory_id") == documents[0]["target"]["factory_id"]
                    and aggregate.get("source_commit") == documents[0]["source"]["commit"]
                    and aggregate.get("source_ref") == documents[0]["source"]["ref"]
                    and aggregate.get("status") in TERMINAL_RECEIPTS | INTERRUPTED_RECEIPTS
                    and isinstance(aggregate.get("children"), list)
                    and sorted((row.get("run_id"), row.get("manifest_hash")) for row in aggregate["children"])
                    == sorted((doc["run_id"], doc["manifest_hash"]) for doc in documents),
                    "reconciliation-cohort-receipt-required")
            require(not completed or aggregate.get("status") == "succeeded"
                    and all(row.get("status") == "succeeded" for row in aggregate["children"]),
                    "reconciliation-completed-cohort-success-required")
            selected[key] = aggregate
        for document in documents:
            fl._validate_manifest(document)
            require(fl.single_writer(document) and document["route"]["repository"] == state["repository"],
                    "reconciliation-native-repository-mismatch")
            view = SimpleNamespace(document=document, settings=document["locks"])
            fl.BlobLocks.verify_enrollment_document(view, state["enrollment"], provider_repository_state.PROTOCOL,
                                                    "repository-exclusive-writer")
            require(set(state["enrollment"]["writers"]) == {document["route"]["writer_id"]},
                    "reconciliation-exclusive-writer-required")
            prefix = "runs/" + document["run_id"]
            claim, run = records.get(prefix + ".claim.json"), records.get(prefix + ".json")
            expected_context = None if completed else {scope: context[scope] for scope in _scope_set([document])}
            require(isinstance(claim, dict) and claim.get("run_id") == document["run_id"]
                    and claim.get("manifest_hash") == document["manifest_hash"]
                    and claim.get("source") == document["source"]
                    and (fl.hash_value(claim.get("lease_context_hash")) if completed else
                         claim.get("lease_context_hash") == fl.digest(expected_context)),
                    "reconciliation-native-execution-claim-required")
            require(isinstance(run, dict) and run.get("execution_claim") == claim
                    and run.get("run_id") == document["run_id"]
                    and run.get("manifest_hash") == document["manifest_hash"]
                    and run.get("status", run.get("state")) in TERMINAL_RECEIPTS | INTERRUPTED_RECEIPTS,
                    "reconciliation-native-run-receipt-required")
            for key, expected in (("target", document["target"]), ("source_commit", document["source"]["commit"])):
                require(key not in run or run[key] == expected, "reconciliation-native-run-binding-mismatch")
            selected[prefix + ".claim.json"], selected[prefix + ".json"] = claim, run
            worker = records.get(prefix + ".worker.json")
            if _remote(document):
                # Missing dispatch acknowledgement is NOT evidence that no worker ran.
                remote = run.get("remote_run")
                require(isinstance(remote, dict) and remote.get("kind") == document["route"]["kind"]
                        and type(remote.get("run_id")) is int and remote["run_id"] > 0
                        and (remote["kind"] == "gha" or type(remote.get("pipeline_id")) is int
                             and remote["pipeline_id"] > 0),
                        "reconciliation-exact-dispatched-run-required")
                require(isinstance(worker, dict), "reconciliation-worker-receipt-missing")
            if worker is not None:
                require(worker.get("run_id") == document["run_id"]
                        and worker.get("manifest_hash") == document["manifest_hash"]
                        and worker.get("target") == document["target"]
                        and worker.get("source_commit") == document["source"]["commit"]
                        and worker.get("status") in TERMINAL_RECEIPTS | INTERRUPTED_RECEIPTS,
                        "reconciliation-worker-binding-mismatch")
                selected[prefix + ".worker.json"] = worker
            if completed:
                require(_remote(document) or worker is None and not run.get("remote_run"),
                        "reconciliation-completed-unexpected-worker")
                require(run.get("status") == "succeeded"
                        and (worker is None or worker.get("status") == "succeeded")
                        and not any(key.startswith("pending_") for receipt in (run, worker or {}) for key in receipt),
                        "reconciliation-completed-native-success-required")
                if cohort:
                    child = next(row for row in aggregate["children"] if row["run_id"] == document["run_id"])
                    require(child.get("execution_claim") == claim,
                            "reconciliation-completed-cohort-claim-mismatch")
        return copy.deepcopy(selected)

    @staticmethod
    def _prior_outer(outer, claim, origin, repository, *, completed):
        require(isinstance(claim, dict), "reconciliation-retained-outer-claim-required")
        if outer.get("claim") == claim:
            require(claim["id"] not in outer.get("history", {}), "reconciliation-prior-claim-already-retired")
            return None
        history = outer.get("history", {}).get(claim["id"])
        observation = history.get("observation", {}) if isinstance(history, dict) else {}
        require(completed and outer.get("claim") is None and isinstance(history, dict)
                and history.get("claim") == claim and observation.get("run_id") == origin["run_id"]
                and observation.get("repository") == repository and observation.get("terminal") is True
                and observation.get("inventory_complete") is True and observation.get("active_operations") == []
                and isinstance(observation.get("evidence_id"), str) and observation["evidence_id"]
                and not observation.get("replacement_operation_id"),
                "reconciliation-retained-or-audited-released-outer-required")
        return copy.deepcopy(history)

    def _evidence(self, stage, record):
        value = self.evidence(copy.deepcopy(stage), copy.deepcopy(record))
        proposal = stage["reconciliation"]
        require(isinstance(value, dict) and all(value.get(key) == proposal[key]
                for key in ("repository", "factory_id", "scopes"))
                and value.get("inventory_complete") is True and value.get("active_operations") == [],
                "reconciliation-live-evidence-incomplete")
        parent = value.get("parent", {})
        require(parent.get("status") == "completed" and all(parent.get(key) == proposal["prior_origin"].get(key)
                for key in ("provider", "run_id", "attempt", "commit", "repository", "ref")),
                "reconciliation-prior-provider-not-terminal")
        children = value.get("children")
        require(isinstance(children, list) and len(children) == len(stage["manifests"]),
                "reconciliation-native-observations-required")
        for document, child in zip(stage["manifests"], children):
            require(child.get("run_id") == document["run_id"]
                    and child.get("manifest_hash") == document["manifest_hash"]
                    and isinstance(child.get("resources"), list) and isinstance(child.get("dependencies"), list)
                    and isinstance(child.get("permissions"), list) and child["permissions"]
                    and fl.guid(child.get("observer_object_id"))
                    and (not _remote(document) or child.get("worker", {}).get("status") == "completed"),
                    "reconciliation-native-observations-incomplete")
            if proposal.get("completed_outcome"):
                identity_only = "foundry_identity_stage" in document.get("deployment", {})
                expected = "continuation-required" if identity_only else "succeeded"
                require(child.get("outcome", {}).get("verified") is True
                        and child["outcome"].get("status") == expected
                        and (not _remote(document) or child["worker"].get("result") in ("success", "succeeded")),
                        "reconciliation-completed-live-outcome-required")
        return copy.deepcopy(value)

    def prepare(self, snapshot, prior_record, new_operation_id):
        identifier(new_operation_id)
        _integrity(prior_record)
        require(new_operation_id != prior_record["operation_id"], "reconciliation-new-review-required")
        _, state, outer, canonical = self._state(snapshot["factory"]["id"])
        prior, documents = self._prior(state, prior_record["operation_id"], snapshot)
        require(prior == prior_record, "reconciliation-prior-record-not-current")
        claim = prior.get("admission_claim")
        require(isinstance(claim, dict)
                and claim.get("operation_id") == prior["operation_id"]
                and claim.get("factory_id") == snapshot["factory"]["id"]
                and claim.get("review_digest") == prior["plan_hash"]
                and claim.get("route") == "pipeline" and claim.get("protocol") == lifecycle_admission.PROTOCOL,
                "reconciliation-retained-outer-claim-required")
        origin = self.review.origin(snapshot)
        previous = prior["plan"].get("origin")
        require(isinstance(origin, dict) and isinstance(previous, dict)
                and origin.get("provider") == previous.get("provider") == self.provider.route["kind"]
                and origin.get("repository") == previous.get("repository")
                and origin.get("run_id") != previous.get("run_id"),
                "reconciliation-new-provider-run-required")
        records = self._native(state, documents)
        completed = state["active"] is None
        require(not completed or len(prior["plan"]["stages"]) == 1,
                "reconciliation-completed-exact-native-stage-required")
        history = self._prior_outer(outer, claim, previous, state["repository"], completed=completed)
        continuation = completed and any("foundry_identity_stage" in doc.get("deployment", {}) for doc in documents)
        scopes = _scope_set(documents)
        require(set(scopes) <= set(claim.get("scopes", [])), "reconciliation-outside-admission-scope")
        proposal = {
            "contract": CONTRACT, "operation_id": new_operation_id, "prior_operation_id": prior["operation_id"],
            "prior_plan_hash": prior["plan_hash"], "prior_snapshot_hash": prior["snapshot_hash"],
            "prior_origin": previous, "origin": origin, "prior_admission_claim": claim,
            "factory_id": snapshot["factory"]["id"], "repository": state["repository"], "scopes": scopes,
            "active_before": state["active"], "native_records": records, "enrollment": state["enrollment"],
            "canonical": canonical, "policy": outer["policy"], "audit_record": AUDIT_PREFIX + new_operation_id + ".json",
            "completed_outcome": completed, "continuation_required": continuation,
            "requires_reprepare": not completed or continuation, "outer_released": history is not None,
            "prior_outer_history": history}
        stage = {"id": "reconcile-retained-claim", "kind": KIND,
                 "manifests": copy.deepcopy(documents), "reconciliation": copy.deepcopy(proposal)}
        stage["reconciliation"]["evidence"] = self._evidence(stage, None)
        return stage

    @staticmethod
    def _record(stage, record):
        _integrity(record)
        require(stage.get("kind") == KIND and record["plan"].get("stages") == [stage]
                and stage.get("reconciliation", {}).get("contract") == CONTRACT
                and stage["reconciliation"].get("operation_id") == identifier(record["operation_id"])
                and record["plan"].get("origin") == stage["reconciliation"].get("origin")
                and record["snapshot_hash"] == stage["reconciliation"].get("prior_snapshot_hash"),
                "reconciliation-authorization-only-review-required")
        relationship = record["plan"].get("recovery_of")
        require(relationship is None or relationship == {
            "operation_id": stage["reconciliation"]["prior_operation_id"],
            "plan_hash": stage["reconciliation"]["prior_plan_hash"]},
            "reconciliation-recovery-parent-mismatch")
        proposal = stage["reconciliation"]
        completed = proposal["active_before"] is None
        continuation = completed and any("foundry_identity_stage" in doc.get("deployment", {})
                                         for doc in stage["manifests"])
        require(proposal.get("completed_outcome") is completed
                and proposal.get("continuation_required") is continuation
                and proposal.get("requires_reprepare") is (not completed or continuation)
                and proposal.get("outer_released") is (proposal.get("prior_outer_history") is not None),
                "reconciliation-completed-outcome-binding-mismatch")

    @staticmethod
    def _stage(record):
        require(isinstance(record.get("plan", {}).get("stages"), list)
                and len(record["plan"]["stages"]) == 1, "reconciliation-authorization-only-review-required")
        stage = record["plan"]["stages"][0]
        RetainedClaimReconciliation._record(stage, record)
        return stage

    @staticmethod
    def _replacement(record, proposal, approval, canonical=None):
        origin = proposal["origin"]
        canonical = proposal["canonical"] if canonical is None else canonical
        return {
            "id": str(uuid5(UUID(record["operation_id"]), CONTRACT)), "protocol": lifecycle_admission.PROTOCOL,
            "factory_id": proposal["factory_id"], "operation_id": record["operation_id"],
            "route": "pipeline", "operation": "cleanup", "review_digest": record["plan_hash"],
            "configuration_revision": canonical["revision"],
            "scopes": sorted(scope.lower() for scope in proposal["policy"]["factories"][proposal["factory_id"]]["scopes"]),
            "identity": {"subject": origin["provider"] + ":" + origin["run_id"] + ":" + str(origin["attempt"]),
                         "run_id": origin["run_id"], "repository": proposal["repository"], "route": "pipeline",
                         "operation_id": record["operation_id"], "review_digest": record["plan_hash"],
                         "authorization_id": digest(approval)}}

    @staticmethod
    def _completed_document(stage, record, children):
        from pipeline_lifecycle_configuration import completed_document
        observed = copy.deepcopy(record)
        observed["status"] = "continuation-required" if stage["reconciliation"]["continuation_required"] else "succeeded"
        observed["stages"] = [{"id": stage["id"], "status": "succeeded", "observation": {
            "status": "succeeded", "verified": True, "children": copy.deepcopy(children)}}]
        return completed_document(observed)

    @staticmethod
    def _owned(outer, canonical, proposal, record):
        claim = record.get("admission_claim")
        require(isinstance(claim, dict) and outer.get("claim") == claim
                and claim.get("protocol") == lifecycle_admission.PROTOCOL
                and claim.get("route") == "pipeline" and claim.get("operation_id") == record["operation_id"]
                and claim.get("factory_id") == proposal["factory_id"]
                and claim.get("review_digest") == record["plan_hash"]
                and claim.get("configuration_revision") == canonical["revision"]
                and claim.get("scopes") == sorted(scope.lower() for scope in
                    outer["policy"]["factories"][proposal["factory_id"]]["scopes"]),
                "reconciliation-owned-replacement-claim-required")

    def acquire(self, record):
        """One reviewed CAS transfers outer ownership without an unclaimed interval."""
        stage = self._stage(record)
        proposal = stage["reconciliation"]
        approval = self.review.verify(record)
        require(isinstance(approval, dict) and all(approval.get(key) == proposal["origin"].get(key)
                and approval.get(key) is not None for key in ("provider", "run_id", "attempt")),
                "reconciliation-new-protected-review-required")
        _, state, outer, canonical = self._state(proposal["factory_id"])
        audit = state["records"].get(proposal["audit_record"])
        if audit is not None:
            claim = audit.get("claim") if isinstance(audit, dict) else None
            require(isinstance(claim, dict) and outer.get("claim") == claim,
                    "reconciliation-audited-admission-not-owned")
            adopted = {**record, "admission_claim": claim}
            self._owned(outer, audit.get("canonical", {}), proposal, adopted)
            self.observe(stage, adopted)
            return copy.deepcopy(claim)
        require(record["operation_id"] not in self.attempted_operations
                and not getattr(self.provider, "write_failed", False)
                and record.get("status") == "prepared"
                and len(record.get("stages", [])) == 1 and record["stages"][0].get("id") == stage["id"]
                and record["stages"][0].get("status") == "pending",
                "reconciliation-observe-before-reprepare-required")
        observed = self._evidence(stage, record)
        require(_evidence_semantics(observed) == _evidence_semantics(proposal["evidence"]),
                "reconciliation-live-state-changed-reprepare-required")
        warnings = _evidence_warnings(observed, proposal["evidence"])
        head, state, outer, canonical = self._state(proposal["factory_id"])
        prior, documents = self._prior(state, proposal["prior_operation_id"], record["snapshot"])
        require(prior["plan_hash"] == proposal["prior_plan_hash"] and documents == stage["manifests"]
                and prior.get("admission_claim") == proposal["prior_admission_claim"]
                and state.get("active") == proposal["active_before"]
                and state.get("enrollment") == proposal["enrollment"]
                and _semantic_document(canonical["document"])
                == _semantic_document(proposal["canonical"]["document"])
                and outer["policy"] == proposal["policy"],
                "reconciliation-reviewed-authority-changed")
        require(self._native(state, documents) == proposal["native_records"],
                "reconciliation-reviewed-native-receipts-changed")
        history = self._prior_outer(outer, proposal["prior_admission_claim"], proposal["prior_origin"],
                                    proposal["repository"], completed=proposal["completed_outcome"])
        require(history == proposal["prior_outer_history"], "reconciliation-reviewed-outer-history-changed")
        if canonical != proposal["canonical"]:
            warnings.append("reconciliation-canonical-generation-drift")
        claim = self._replacement(record, proposal, approval, canonical)
        updated = copy.deepcopy(state)
        updated["active"] = None
        replacement_outer = updated["records"][lifecycle_admission.RECORD]
        replacement_outer["claim"] = copy.deepcopy(claim)
        retired = history if history is not None else {
            "claim": copy.deepcopy(proposal["prior_admission_claim"]), "observation": {
            "run_id": proposal["prior_origin"]["run_id"], "repository": proposal["repository"],
            "terminal": True, "inventory_complete": True, "active_operations": [],
            "evidence_id": digest(observed), "status": (
                "observed-native-success" if proposal["completed_outcome"] else "reconciled-not-completed"),
            "replacement_operation_id": record["operation_id"], "audit_record": proposal["audit_record"]}}
        replacement_outer["history"][proposal["prior_admission_claim"]["id"]] = retired
        updated["records"][proposal["audit_record"]] = {
            "schema": 1, "contract": CONTRACT, "operation_id": record["operation_id"],
            "plan_hash": record["plan_hash"], "stage_hash": digest(stage), "previous_head": head,
            "active_before": copy.deepcopy(state["active"]), "claim": copy.deepcopy(claim),
            "retired": copy.deepcopy(retired), "canonical": copy.deepcopy(canonical), "warnings": warnings,
            "approval": copy.deepcopy(approval), "observed": observed, "reconciled_at": now(),
            "native_receipts_preserved": {key: digest(value) for key, value in proposal["native_records"].items()},
            "runtime_ready": proposal["completed_outcome"] and all(
                child.get("outcome", {}).get("runtime_ready") is True for child in observed["children"]),
            "requires_reprepare": proposal["requires_reprepare"],
            "completed_outcome": proposal["completed_outcome"], "continuation_required": proposal["continuation_required"],
            "azure_writes": False}
        self.attempted_operations.add(record["operation_id"])
        try:
            self.provider.replace(head, updated)
        except Exception:
            result = self.observe(stage, {**record, "admission_claim": claim})
            require(result.get("verified") is True, "reconciliation-acquisition-outcome-uncertain")
            return copy.deepcopy(claim)
        self.observe(stage, {**record, "admission_claim": claim})
        return copy.deepcopy(claim)

    def execute(self, stage, record):
        self._record(stage, record)
        return self.observe(stage, record)

    def observe(self, stage, record):
        self._record(stage, record)
        proposal = stage["reconciliation"]
        head, state, outer, canonical = self._state(proposal["factory_id"])
        audit = state["records"].get(proposal["audit_record"])
        if audit is None:
            return {"status": "reconciliation-required", "verified": False,
                    "audit_record": proposal["audit_record"], "requires_reprepare": True}
        require(isinstance(audit, dict) and audit.get("contract") == CONTRACT
                and audit.get("operation_id") == record["operation_id"] and audit.get("plan_hash") == record["plan_hash"]
                and audit.get("stage_hash") == digest(stage) and audit.get("active_before") == proposal["active_before"]
                and audit.get("claim") == record.get("admission_claim")
                and _evidence_semantics(audit.get("observed")) == _evidence_semantics(proposal["evidence"]),
                "reconciliation-audit-binding-mismatch")
        claim = record["admission_claim"]
        baseline = audit.get("canonical")
        require(isinstance(baseline, dict) and isinstance(baseline.get("document"), dict)
                and baseline.get("revision") == digest(baseline["document"])
                and _semantic_document(baseline["document"]) == _semantic_document(proposal["canonical"]["document"]),
                "reconciliation-audited-canonical-mismatch")
        require(claim == self._replacement(record, proposal, audit["approval"], baseline)
                and audit.get("retired", {}).get("claim") == proposal["prior_admission_claim"]
                and outer.get("history", {}).get(proposal["prior_admission_claim"]["id"]) == audit["retired"],
                "reconciliation-atomic-handover-unverified")
        require(outer.get("claim") == claim or outer.get("claim") is None and any(
            item.get("claim") == claim for item in outer.get("history", {}).values()),
            "reconciliation-outer-ownership-changed")
        require(state.get("active") is None and state["enrollment"] == proposal["enrollment"]
                and outer["policy"] == proposal["policy"]
                and all(state["records"].get(key) == value for key, value in proposal["native_records"].items())
                and audit.get("native_receipts_preserved") == {
                    key: digest(value) for key, value in proposal["native_records"].items()},
                "reconciliation-durable-result-changed")
        observed = self._evidence(stage, record)
        require(not proposal["completed_outcome"]
                or _evidence_semantics(observed) == _evidence_semantics(proposal["evidence"]),
                "reconciliation-completed-live-state-changed")
        warnings = [*audit.get("warnings", []), *_evidence_warnings(observed, proposal["evidence"])]
        if any(child.get("outcome", {}).get("diagnostic_drift") for child in observed["children"]):
            warnings.append("reconciliation-completed-receipt-diagnostic-drift")
        if canonical != baseline and _semantic_document(canonical["document"]) == _semantic_document(baseline["document"]):
            warnings.append("reconciliation-canonical-generation-drift")
        children = [{"native": {}, "worker": copy.deepcopy(receipt)} for key, receipt in
                    proposal["native_records"].items() if key.endswith(".worker.json")
                    and receipt.get("status") == "succeeded"]
        if proposal["completed_outcome"]:
            children = [{"native": copy.deepcopy(proposal["native_records"]["runs/" + doc["run_id"] + ".json"]),
                         "worker": copy.deepcopy(proposal["native_records"].get("runs/" + doc["run_id"] + ".worker.json")),
                         "observer_object_id": child["observer_object_id"]}
                        for doc, child in zip(stage["manifests"], observed["children"])]
        if _semantic_document(canonical["document"]) != _semantic_document(proposal["canonical"]["document"]):
            require(proposal["completed_outcome"], "reconciliation-durable-result-changed")
            require(_semantic_document(canonical["document"])
                    == _semantic_document(self._completed_document(stage, record, children)),
                    "reconciliation-completed-canonical-mismatch")
        return {"status": "succeeded", "verified": True, "audit_record": proposal["audit_record"],
                "provider_head": head, "canonical": copy.deepcopy(canonical), "azure_writes": False,
                "runtime_ready": False, "requires_reprepare": proposal["requires_reprepare"],
                "completed_outcome": proposal["completed_outcome"], "continuation_required": proposal["continuation_required"],
                "outer_released": proposal["outer_released"],
                "admission_claim": copy.deepcopy(claim), "children": children,
                "live_evidence": observed,
                "warnings": sorted(set(warnings)),
                "residual_resources": [copy.deepcopy(row) for child in observed["children"]
                                       for row in child["resources"] if row.get("present") is not False]}

    def prepare_residual(self, snapshot, reconciliation_record, new_operation_id, *, planner):
        identifier(new_operation_id)
        _integrity(reconciliation_record)
        require(new_operation_id != reconciliation_record["operation_id"],
                "reconciliation-residual-new-operation-required")
        stages = reconciliation_record["plan"]["stages"]
        require(len(stages) == 1 and stages[0].get("kind") == KIND,
                "reconciliation-residual-parent-required")
        stage = stages[0]
        result = self.observe(stage, reconciliation_record)
        require(result.get("requires_reprepare") is True, "reconciliation-completed-native-replay-forbidden")
        expected = reconciliation_record["snapshot"]
        if result.get("completed_outcome") is True:
            from pipeline_lifecycle_recovery import finalized_snapshot
            require(result.get("continuation_required") is True
                    and result.get("canonical") == reconciliation_record.get("configuration"),
                    "reconciliation-completed-continuation-binding-mismatch")
            expected = finalized_snapshot(reconciliation_record)
        require(result.get("verified") is True and snapshot == expected
                and reconciliation_record.get("status") == "continuation-required"
                and reconciliation_record.get("admission", {}).get("status") == "released"
                and reconciliation_record.get("finalization", {}).get("status") == "succeeded",
                "reconciliation-residual-finalization-required")
        _, state, outer, _ = self._state(stage["reconciliation"]["factory_id"])
        require(state["records"].get(_journal_key(reconciliation_record["operation_id"])) == reconciliation_record,
                "reconciliation-durable-finalization-required")
        require(outer.get("claim") is None, "reconciliation-residual-outer-claim-active")
        # observe above re-reads native resources, including after a lost CAS response.
        plan = planner.prepare(copy.deepcopy(snapshot), new_operation_id)
        require(isinstance(plan, dict) and plan.get("stages")
                and all(child.get("kind") == "lifecycle" and child.get("manifests") for child in plan["stages"]),
                "reconciliation-fresh-native-plan-required")
        old_runs = {doc["run_id"] for doc in stage["manifests"]}
        require(all(doc["run_id"] not in old_runs for child in plan["stages"] for doc in child.get("manifests", [])),
                "reconciliation-native-replay-forbidden")
        for child in plan["stages"]:
            for document in child["manifests"]:
                fl.validate_manifest(document)
        plan = copy.deepcopy(plan)
        plan["residual_of"] = {"operation_id": reconciliation_record["operation_id"],
                               "plan_hash": reconciliation_record["plan_hash"], "audit_record": result["audit_record"]}
        return plan


class NativeReconciliationEvidence:
    """Read actual provider termination, ARM inventory, owners, permissions and dependencies."""

    def __init__(self, review, *, cloud_factory=None):
        self.review, self.cloud_factory = review, cloud_factory

    @staticmethod
    def _resource_facts(resource_id, body):
        require(isinstance(body, dict) and str(body.get("id", "")).lower() == resource_id.lower(),
                "reconciliation-live-resource-identity-mismatch")
        kind = ("microsoft.resources/resourcegroups" if fl.RG_ID.fullmatch(resource_id)
                else fl.resource_type_from_id(resource_id))
        require(str(body.get("type", kind)).lower() == kind.lower(),
                "reconciliation-live-resource-type-mismatch")
        properties, identity = body.get("properties") or {}, body.get("identity") or {}
        require(isinstance(properties, dict) and isinstance(identity, dict), "reconciliation-resource-identity-invalid")
        principal_keys = ("principalId", "tenantId", "clientId", "objectId", "applicationId", "resourceGuid")

        def principals(value):
            result = {key: value[key] for key in principal_keys if value.get(key) is not None}
            require(all(fl.guid(item) for item in result.values()), "reconciliation-resource-principal-invalid")
            return {key: item.lower() for key, item in result.items()}

        assigned = identity.get("userAssignedIdentities") or {}
        require(isinstance(assigned, dict) and all(fl.NESTED_ID.fullmatch(key) and isinstance(item, dict)
                                                 for key, item in assigned.items()),
                "reconciliation-assigned-identities-invalid")
        access = properties.get("accessPolicies", [])
        require(isinstance(access, list) and all(isinstance(item, dict) for item in access),
                "reconciliation-resource-access-policies-invalid")
        return {
            "id": resource_id.lower(), "group": fl.arm_scope(resource_id), "type": kind.lower(),
            "managed_by": str(body.get("managedBy", "")).lower(), "principals": principals(properties),
            "identity": {"type": identity.get("type"), **principals(identity),
                         "user_assigned": {key.lower(): principals(item) for key, item in assigned.items()}},
            "access_policies": [{**principals(item), "permissions": item.get("permissions")} for item in access],
            "federation": {key: properties[key] for key in ("issuer", "subject", "audiences") if key in properties},
        }

    @staticmethod
    def _references(resource_id, body):
        references = set()

        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    visit(key)
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, str) and value.lower() != resource_id.lower() and (
                    fl.RG_ID.fullmatch(value) or fl.NESTED_ID.fullmatch(value)):
                references.add(value.lower())
        visit(body)
        return sorted(references)

    @staticmethod
    def _terminal(cloud, route, origin, document=None, remote=None):
        run_id = str(origin["run_id"] if remote is None else remote["run_id"])
        require(run_id.isdigit() and int(run_id) > 0, "reconciliation-provider-run-id-required")
        if route["kind"] == "gha":
            repository = urlsplit(route["repository"]).path.strip("/")
            _, _, run = cloud.state_request("gha", "GET", "repos/" + repository + "/actions/runs/" + run_id, None, (200,))
            expected_ref = origin["ref"].removeprefix("refs/heads/").removeprefix("refs/tags/")
            if remote is not None:
                expected_ref = "aifactory-runs/" + document["run_id"]
            require(isinstance(run, dict) and str(run.get("id")) == run_id
                    and run.get("head_sha") == (route["commit"] if remote else origin["commit"])
                    and run.get("run_attempt") == (1 if remote else origin["attempt"])
                    and run.get("repository", {}).get("full_name") == repository
                    and run.get("head_branch") == expected_ref
                    and (remote is None or run.get("display_title") == "factory-lifecycle [" + document["run_id"] + "]"),
                    "reconciliation-provider-run-binding-mismatch")
            require(run.get("status") == "completed" and run.get("conclusion") in {
                "success", "failure", "cancelled", "timed_out", "neutral", "skipped", "action_required", "stale"},
                "reconciliation-provider-run-not-terminal")
            result = run["conclusion"]
        else:
            org, project, _, repository_name = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
            base = "https://dev.azure.com/" + quote(org) + "/" + quote(project) + "/_apis"
            _, _, repository = cloud.state_request("ado", "GET", base + "/git/repositories/"
                                                  + quote(repository_name) + "?api-version=7.1", None, (200,))
            require(isinstance(repository, dict) and fl.guid(repository.get("id"))
                    and repository.get("remoteUrl", "").lower() == route["repository"].lower(),
                    "reconciliation-provider-repository-unverified")
            _, _, run = cloud.state_request("ado", "GET", base + "/build/builds/" + run_id + "?api-version=7.1", None, (200,))
            require(isinstance(run, dict) and str(run.get("id")) == run_id
                    and run.get("sourceVersion") == (route["commit"] if remote else origin["commit"])
                    and run.get("sourceBranch") == (route["ref"] if remote else origin["ref"])
                    and run.get("repository", {}).get("id") == repository["id"]
                    and (remote is None or run.get("definition", {}).get("id") == remote["pipeline_id"]),
                    "reconciliation-provider-run-binding-mismatch")
            require(run.get("status") == "completed" and run.get("result") in {
                "succeeded", "partiallySucceeded", "failed", "canceled"}, "reconciliation-provider-run-not-terminal")
            result = run["result"]
        return {**copy.deepcopy(origin if remote is None else remote), "status": "completed", "result": result}

    @staticmethod
    def _permissions(cloud, scope):
        _, _, value = cloud.request("GET", fl.ARM + quote(scope, safe="/().-_")
                                    + "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01", fl.ARM)
        require(isinstance(value, dict) and isinstance(value.get("value"), list) and value["value"]
                and not value.get("nextLink"), "reconciliation-complete-permissions-required")
        action = "microsoft.resources/subscriptions/resourcegroups/read"
        allowed = False
        for row in value["value"]:
            require(isinstance(row, dict) and isinstance(row.get("actions"), list)
                    and isinstance(row.get("notActions"), list)
                    and all(isinstance(item, str) for item in row["actions"] + row["notActions"]),
                    "reconciliation-permissions-invalid")
            allowed |= any(fnmatch.fnmatchcase(action, item.lower()) for item in row["actions"]) and not any(
                fnmatch.fnmatchcase(action, item.lower()) for item in row["notActions"])
        require(allowed, "reconciliation-read-permission-required")
        return {"scope": scope, "permissions": value["value"]}

    @staticmethod
    def _pending(cloud, document, receipts):
        proofs = []
        rows = {row["id"].lower(): row for row in document.get("deletion", {}).get("resources", [])
                + document.get("deletion", {}).get("resource_groups", [])}
        subscription = "/subscriptions/" + document["target"]["subscription_id"]
        for receipt in receipts:
            require(not receipt.get("pending_foundry_gate"), "reconciliation-foundry-gate-proof-required")
            for name in ("pending_resource", "pending_resource_group"):
                if name not in receipt:
                    continue
                resource_id = receipt[name]
                require(isinstance(resource_id, str) and resource_id.lower() in rows,
                        "reconciliation-pending-delete-outside-manifest")
                row = rows[resource_id.lower()]
                if fl.RG_ID.fullmatch(resource_id):
                    absent = fl.absent_groups(cloud, [resource_id], "reconciliation-pending-delete-absence-unverified")
                    require(resource_id in absent, "reconciliation-pending-delete-unverified")
                else:
                    status, _, body = cloud.arm("GET", resource_id, row.get("api_version", fl.RG_API), allowed=(200, 404))
                    require(status == 404, "reconciliation-pending-delete-unverified")
                    _not_found(body, ("ResourceNotFound", "ParentResourceNotFound"),
                               "reconciliation-pending-delete-absence-unverified")
                # The native receipt predates DELETE and has no terminal response.
                # A still-present resource cannot prove its asynchronous delete ended.
                proofs.append({"resource_id": resource_id.lower(), "present": False})
            pending = receipt.get("pending_deployment")
            if pending is not None:
                require(isinstance(pending, str), "reconciliation-pending-deployment-invalid")
                path = urlsplit(pending)
                require(not path.scheme and not path.netloc and not path.fragment
                        and path.path.lower().startswith(subscription.lower() + "/")
                        and "/providers/microsoft.resources/deployments/" in path.path.lower()
                        and (path.path.lower().startswith(subscription.lower()
                            + "/providers/microsoft.resources/deployments/") or
                            fl.arm_scope(path.path).lower() in _scope_set([document])),
                        "reconciliation-pending-deployment-outside-manifest")
                status, _, body = cloud.arm("GET", path.path, "2022-09-01", allowed=(200, 404))
                if status == 404:
                    _not_found(body, ("DeploymentNotFound",), "reconciliation-pending-deployment-absence-unverified")
                require(status == 404 or isinstance(body, dict)
                        and body.get("properties", {}).get("provisioningState") in ("Succeeded", "Failed", "Canceled"),
                        "reconciliation-pending-deployment-not-terminal")
                proofs.append({"deployment_id": path.path.lower(), "present": status == 200,
                               "state": body.get("properties", {}).get("provisioningState") if status == 200 else None})
        if _remote(document):
            _, _, page = cloud.request("GET", fl.ARM + subscription
                                      + "/providers/Microsoft.Resources/deployments?api-version=2022-09-01", fl.ARM)
            require(isinstance(page, dict) and isinstance(page.get("value"), list) and not page.get("nextLink"),
                    "reconciliation-complete-subscription-deployments-required")
            require(all(isinstance(row, dict) and row.get("properties", {}).get("provisioningState")
                        in ("Succeeded", "Failed", "Canceled") for row in page["value"]),
                    "reconciliation-subscription-deployment-not-terminal")
        return proofs

    @classmethod
    def _completed_outcome(cls, cloud, document, records, bodies, absent_scopes, *, worker=None):
        prefix = "runs/" + document["run_id"]
        native = records[prefix + ".json"]
        def receipt_read(method, path, *args, **kwargs):
            require(method == "GET" and path in records, "reconciliation-completed-receipt-read-only")
            return 200, {}, copy.deepcopy(records[path])

        receipts = SimpleNamespace(request=receipt_read)
        if worker is None and _remote(document):
            worker = fl.verify_worker_receipt(receipts, document)
        outcome = {"status": "succeeded", "verified": True, "effects": [], "diagnostic_drift": []}
        if document["operation"] == "delete":
            rows = document["deletion"]["resources"] + document["deletion"]["resource_groups"]
            removed = {row["id"].lower() for row in rows if row["delete"]}
            already_absent = {row["id"].lower() for row in rows if row["delete"] and row.get("already_absent")}
            require(removed - already_absent == set(map(str.lower, native.get("deleted_resources", [])
                    + native.get("deleted_resource_groups", [])))
                    and already_absent <= set(map(str.lower, native.get("observed_absent", []))) <= removed,
                    "reconciliation-completed-delete-receipt-incomplete")
            for row in rows:
                key = row["id"].lower()
                if row["delete"]:
                    if fl.arm_scope(key) not in absent_scopes:
                        status, _, body = cloud.arm("GET", row["id"], row.get("api_version", fl.RG_API),
                                                     allowed=(200, 404))
                        require(status == 404, "reconciliation-completed-delete-reappeared")
                        _not_found(body, ("ResourceGroupNotFound",) if fl.RG_ID.fullmatch(key)
                                   else ("ResourceNotFound", "ParentResourceNotFound"),
                                   "reconciliation-completed-delete-absence-unverified")
                    outcome["effects"].append({"id": key, "present": False})
                else:
                    status, _, body = cloud.arm("GET", row["id"], row.get("api_version", fl.RG_API),
                                                 allowed=(200, 404))
                    require(status == 200, "reconciliation-completed-retained-resource-missing")
                    facts = cls._resource_facts(key, body)
                    tags = {name.lower(): value for name, value in (body.get("tags") or {}).items()}
                    require(all(tag not in tags or tags[tag] == row.get("owner", {}).get(name)
                                for name, tag in fl.TAG_KEYS.items()),
                            "reconciliation-completed-retained-owner-changed")
                    before = document["deletion"].get("bodies", {}).get(key)
                    if before is not None:
                        require(cls._resource_facts(key, before) == facts,
                                "reconciliation-completed-retained-identity-changed")
                    outcome["effects"].append({"id": key, "present": True, "resource_identity": facts})
            return outcome

        identity_only = "foundry_identity_stage" in document["deployment"]
        require(bool(native.get("continuation_required") or native.get("completion") == "identity-only") == identity_only,
                "reconciliation-completed-continuation-receipt-mismatch")
        if identity_only:
            fl.verify_foundry_identity_receipt(document, worker)
            proof = worker["foundry_identity_receipt"]
            status, _, body = cloud.arm("GET", proof["resource_id"], fl.FOUNDRY_MI_API, allowed=(200, 404))
            require(status == 200, "reconciliation-completed-identity-missing")
            facts = cls._resource_facts(proof["resource_id"], body)
            require(facts["group"] == proof["resource_group"]
                    and all(facts["principals"].get(live) == proof["identity"].get(saved) for live, saved in (
                        ("principalId", "principal_id"), ("clientId", "client_id"), ("tenantId", "tenant_id"))),
                    "reconciliation-completed-identity-changed")
            group = bodies.get(proof["resource_group"])
            require(isinstance(group, dict) and all(group.get("tags", {}).get(key) == value for key, value in
                    (proof.get("group_tags_update") or {}).get("after", {}).items()),
                    "reconciliation-completed-identity-group-changed")
            if fl.digest(body) != proof["body_hash"]:
                outcome["diagnostic_drift"].append(proof["resource_id"])
            outcome["status"] = "continuation-required"
            outcome["effects"].append({"id": proof["resource_id"], "present": True, "resource_identity": facts})
            return outcome

        if "foundry_lifecycle" in document["deployment"]:
            from pipeline_lifecycle_adapters import observe_foundry_runtime
            observe_foundry_runtime(cloud, document, worker)
            outcome["runtime_ready"] = True
        for step, receipt in zip(document["deployment"]["steps"], worker["deployments"]):
            endpoint = fl.deployment_endpoint(document, step)
            expected_id = endpoint.removeprefix(fl.ARM)
            require(str(receipt.get("id", "")).lower() == expected_id.lower(),
                    "reconciliation-completed-deployment-binding-mismatch")
            _, _, body = cloud.request("GET", endpoint + "?api-version=2022-09-01", fl.ARM)
            require(isinstance(body, dict) and str(body.get("id", "")).lower() == expected_id.lower()
                    and body.get("properties", {}).get("provisioningState") == "Succeeded",
                    "reconciliation-completed-deployment-unverified")
            outcome["effects"].append({"id": expected_id.lower(), "state": "Succeeded"})
        cache = {}
        for row in worker["resource_groups"] + worker["ownership"]:
            key = row["resource_id"].lower()
            body = bodies.get(key)
            require(isinstance(body, dict) and fl.arm_scope(key) in {
                scope.lower() for scope in document["locks"]["scopes"]},
                "reconciliation-completed-owned-resource-missing")
            facts = cls._resource_facts(key, body)
            require(body.get("properties", {}).get("provisioningState") in (None, "Succeeded"),
                    "reconciliation-completed-resource-not-succeeded")
            owner = fl.verified_receipt_owner(receipts, {
                "run_id": document["run_id"], "receipt_hash": fl.digest(worker)},
                key, fl.resource_digest(body), cache, drift=outcome["diagnostic_drift"])
            tags = {name.lower(): value for name, value in (body.get("tags") or {}).items()}
            require(all(tag not in tags or tags[tag] == owner.get(name) for name, tag in fl.TAG_KEYS.items()),
                    "reconciliation-completed-resource-owner-changed")
            outcome["effects"].append({"id": key, "present": True, "owner": owner, "resource_identity": facts})
        for key, row in document["deployment"].get("bootstrap_foundation", {}).get("resources", {}).items():
            if row.get("disposition") == "preserve":
                require(key.lower() in bodies, "reconciliation-completed-preserved-resource-missing")
                outcome["effects"].append({"id": key.lower(), "present": True,
                                           "resource_identity": cls._resource_facts(key, bodies[key.lower()])})
        return outcome

    def __call__(self, stage, record):
        from pipeline_lifecycle_adapters import operation_identity
        from pipeline_lifecycle_cloud import PipelineCloud
        proposal = stage["reconciliation"]
        current = self.review.origin(record["snapshot"]) if record is not None else proposal["origin"]
        require(current.get("provider") == proposal["origin"]["provider"]
                and current.get("repository") == proposal["origin"]["repository"]
                and current.get("run_id") != proposal["prior_origin"]["run_id"],
                "reconciliation-authenticated-observer-required")
        result = {key: copy.deepcopy(proposal[key]) for key in ("repository", "factory_id", "scopes")}
        result.update(inventory_complete=True, active_operations=[], children=[])
        for original in stage["manifests"]:
            document = copy.deepcopy(original)
            cloud = self.cloud_factory(document) if self.cloud_factory else PipelineCloud(document, current)
            if hasattr(cloud, "origin"):
                cloud.origin = copy.deepcopy(current)
            cloud.expected_object_id = operation_identity(cloud, document["target"])
            cloud.verify_identity()
            locks = fl.coordination(cloud, document)
            locks.verify_enrollment()
            cloud.assert_no_active_runs(locks.enrollment)
            parent = self._terminal(cloud, document["route"], proposal["prior_origin"])
            require("parent" not in result or result["parent"] == parent, "reconciliation-provider-parent-changed")
            result["parent"] = parent
            native = proposal["native_records"]["runs/" + document["run_id"] + ".json"]
            worker = self._terminal(cloud, document["route"], proposal["prior_origin"], document,
                                    native["remote_run"]) if _remote(document) else None
            receipts = [native, proposal["native_records"].get("runs/" + document["run_id"] + ".worker.json", {})]
            pending = self._pending(cloud, document, receipts)
            present, absent, permissions = [], [], []
            absent_scopes = set(fl.absent_groups(cloud, _scope_set([document]),
                                                 "reconciliation-resource-group-absence-unverified"))
            for scope in _scope_set([document]):
                if scope not in absent_scopes:
                    status, _, body = cloud.arm("GET", scope, fl.RG_API, allowed=(200, 404))
                    require(status == 200 and isinstance(body, dict) and str(body.get("id", "")).lower() == scope,
                            "reconciliation-scope-identity-mismatch")
                    cloud.assert_no_active_deployments(scope)
                    present.append(scope)
                    permissions.append(self._permissions(cloud, scope))
                else:
                    require(scope not in {value.lower() for value in document["locks"]["common_dependencies"]},
                            "reconciliation-common-dependency-missing")
                    absent.append({"id": scope, "present": False, "owner": {
                        key: document["target"][key] for key in ("factory_id", "scaleset_id")}})
                    permissions.append(self._permissions(cloud, "/".join(scope.split("/")[:3])))
            closure, bodies = fl.collect_resource_closure(cloud, present)
            own = {value.lower() for value in document["locks"]["scopes"]}
            owners, resources, dependencies = {}, list(absent), []
            for scope in present:
                if scope in own:
                    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
                    fl.verify_group_ownership(bodies[scope], owner, bodies)
                    owners[scope] = owner
            for section in ("groups", "resources"):
                for key, metadata in sorted(closure[section].items()):
                    body = bodies[key]
                    require(body.get("properties", {}).get("provisioningState") in (
                        None, "Succeeded", "Failed", "Canceled"), "reconciliation-resource-not-terminal")
                    tags = {name.lower(): value for name, value in (body.get("tags") or {}).items()}
                    owner = {name: tags[tag] for name, tag in fl.TAG_KEYS.items() if tag in tags}
                    item = {"id": key, "present": True, "metadata": copy.deepcopy(metadata),
                            "owner": owner or owners.get(key, {}),
                            "ownership_source": "tags" if owner else "observed-retained",
                            "resource_identity": self._resource_facts(key, body),
                            "references": self._references(key, body)}
                    (resources if fl.arm_scope(key).lower() in own else dependencies).append(item)
            child = {
                "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
                "observer_object_id": cloud.expected_object_id,
                "deployment_object_id": document["identity"].get("deployment_object_id"),
                "worker": worker, "resources": resources, "dependencies": dependencies,
                "permissions": permissions, "pending_observations": pending, "closure": fl.frozen_closure(closure)}
            if proposal.get("completed_outcome"):
                child["outcome"] = self._completed_outcome(
                    cloud, document, proposal["native_records"], bodies, absent_scopes)
            result["children"].append(child)
        return result
