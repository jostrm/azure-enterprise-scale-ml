"""Provider-GET-only completion observer; no Azure identity or mutable state port."""
import re
import time

from pipeline_dispatch import (
    DispatchError, GHA_WORKFLOW, ProviderReceiptReader, ProviderTransport,
    _ado_definition, _gha_identity, _pages, require, validate_binding,
)


class NativeJobs:
    def __init__(self, context, *, transport=None):
        self.provider = context["provider"]
        self.binding = {"schema": 1, "provider": self.provider, "repository": context["repository"],
                        "consumer_commit": context["consumer_commit"]}
        self.base = validate_binding({"provider": self.provider}, self.binding)
        self.transport = transport or ProviderTransport(self.provider, self.base)
        self.workflow_id = None

    def get(self, url):
        status, _, value = self.transport.request("GET", url)
        require(status == 200, "authenticated-provider-observation-required")
        return value

    def run(self, record):
        context, origin = record["plan"]["provider_context"], record["plan"]["origin"]
        require(context["provider"] == self.provider and context["repository"] == self.binding["repository"]
                and context["consumer_commit"] == self.binding["consumer_commit"]
                and type(context.get("run_id")) is int and context["run_id"] > 0
                and type(context.get("run_attempt")) is int and context["run_attempt"] == 1,
                "observer-route-changed")
        run_id = context["run_id"]
        if self.provider == "gha":
            if self.workflow_id is None:
                workflow = self.get(self.base + "/actions/workflows/pipelines-only-gha.yml")
                require(workflow.get("path") == GHA_WORKFLOW and workflow.get("state") == "active"
                        and type(workflow.get("id")) is int, "fixed-provider-workflow-required")
                self.workflow_id = workflow["id"]
            run = self.get(f"{self.base}/actions/runs/{run_id}")
            correlation = "" if run.get("display_title") == "pipelines-only []" else context["correlation_id"]
            _gha_identity(run, binding=self.binding, workflow=self.workflow_id, correlation=correlation, run_id=run_id)
        else:
            run = self.get(f"{self.base}/build/builds/{run_id}?api-version=7.1")
            require(run.get("id") == run_id and run.get("sourceVersion") == context["consumer_commit"]
                    and run.get("sourceBranch") == origin["ref"]
                    and run.get("repository", {}).get("url", "").lower() == context["repository"].lower()
                    and run.get("repository", {}).get("type") == "TfsGit"
                    and type(run.get("definition", {}).get("id")) is int, "provider-run-identity-mismatch")
            if self.workflow_id is None:
                self.workflow_id = _ado_definition(
                    self.transport, self.base, dict(self.binding, pipeline_id=run["definition"]["id"]))
            require(run["definition"]["id"] == self.workflow_id, "provider-run-identity-mismatch")
        return run

    def not_failed(self, record):
        run = self.run(record)
        active = (("queued", "in_progress", "waiting", "pending", "requested") if self.provider == "gha"
                  else ("notStarted", "inProgress", "postponed"))
        result = run.get("conclusion" if self.provider == "gha" else "result")
        require(run.get("status") in active and result is None
                or run.get("status") == "completed" and result == ("success" if self.provider == "gha" else "succeeded"),
                "scenario-provider-run-unsuccessful")

    def terminal(self, record, *, finalizer_only=False):
        """Check exact native mutators, never wait on the hosted completion job."""
        self.not_failed(record)
        context = record["plan"]["provider_context"]
        operation, plan_hash = record["operation_id"], record["plan_hash"]
        proof = record.get("finalization", {}).get("proof", {})
        run_id = context["run_id"]
        if self.provider == "gha":
            rows = _pages(self.transport, f"{self.base}/actions/runs/{run_id}/jobs?filter=latest", "jobs")
            names = ["prepare", f"Execute reviewed {operation} / {plan_hash}", f"Finalize reviewed {operation} / {plan_hash}"]
            selected = []
            for name in names[-1:] if finalizer_only else names:
                matches = [row for row in rows if row.get("name") == name]
                require(len(matches) <= 1, "observer-native-job-ambiguous")
                if not matches:
                    return False
                row = matches[0]
                require(row.get("run_id") == run_id and row.get("run_attempt") == 1
                        and row.get("head_sha") == context["consumer_commit"], "observer-native-job-binding-mismatch")
                selected.append(row)
            finalizer = selected[-1]
            require(finalizer.get("id") == proof.get("job_id") and proof.get("job_id") is not None,
                    "observer-finalizer-proof-mismatch")
            if not all(row.get("status") == "completed" for row in selected):
                return False
            require(all(row.get("conclusion") == "success" for row in selected), "observer-mutating-job-unsuccessful")
        else:
            timeline = self.get(f"{self.base}/build/builds/{run_id}/timeline?api-version=7.1")
            rows = timeline.get("records", [])
            require(isinstance(rows, list) and all(isinstance(row, dict) and row.get("id") for row in rows),
                    "observer-native-timeline-invalid")
            by_id = {row["id"]: row for row in rows}
            require(len(by_id) == len(rows), "observer-native-job-ambiguous")
            selected = []
            pairs = [("PrepareOperation", "Prepare"), ("ExecuteReviewedOperation", "Execute"),
                     ("FinalizeReviewedOperation", "Finalize")]
            for name, stage_name in pairs[-1:] if finalizer_only else pairs:
                matches = [row for row in rows if row.get("type") == "Job" and row.get("identifier") == name]
                require(len(matches) <= 1, "observer-native-job-ambiguous")
                if not matches:
                    return False
                row, visited = matches[0], set()
                ancestor = row
                while True:
                    require(ancestor.get("attempt") == 1 and not ancestor.get("previousAttempts"),
                            "observer-native-job-rerun")
                    if not ancestor.get("parentId"):
                        break
                    require(ancestor["id"] not in visited and ancestor["parentId"] in by_id,
                            "observer-native-job-ancestry-invalid")
                    visited.add(ancestor["id"])
                    ancestor = by_id[ancestor["parentId"]]
                require(ancestor.get("type") == "Stage" and ancestor.get("name") == stage_name,
                        "observer-native-job-binding-mismatch")
                selected.append(row)
            require(selected[-1].get("id") == proof.get("job_id") and proof.get("job_id") is not None,
                    "observer-finalizer-proof-mismatch")
            if not all(row.get("state") == "completed" for row in selected):
                return False
            require(all(row.get("result") == "succeeded" for row in selected), "observer-mutating-job-unsuccessful")
        return True


def _scheduled_chain(snapshot, root, jobs):
    from pipeline_lifecycle_adapters import RepositoryJournal
    records, seen = [root], {root["operation_id"]}
    current = root
    while True:
        jobs.not_failed(current)
        dispatched = current.get("provider_continuation")
        if not dispatched or dispatched.get("status") == "dispatching":
            return records
        context = current["plan"]["provider_context"]
        require(dispatched.get("status") == "dispatched" and type(dispatched.get("run_id")) is int
                and dispatched["run_id"] > 0 and dispatched["run_id"] != context["run_id"]
                and re.fullmatch(r"[a-f0-9]{32}", dispatched.get("correlation_id", "")),
                "observer-continuation-dispatch-invalid")
        expected = dict(context, run_id=dispatched["run_id"], correlation_id=dispatched["correlation_id"])
        jobs.not_failed({"plan": {"provider_context": expected, "origin": current["plan"]["origin"]}})
        child_id = current.get("continuation_child")
        if child_id is None or RepositoryJournal.key(child_id) not in snapshot.state["records"]:
            return records
        require(child_id not in seen and len(seen) < 8, "continuation-chain-invalid")
        seen.add(child_id)
        _, child = snapshot._load(child_id)
        require(child["plan"].get("provider_context") == expected and child["plan"].get("continuation_of") == {
            "operation_id": current["operation_id"], "plan_hash": current["plan_hash"]},
            "observer-continuation-binding-mismatch")
        records.append(child)
        current = child


def wait_for_completion(operation_id, plan_hash, context, *, reader=None, transport=None,
                        max_polls=1200, poll_seconds=15, sleep=time.sleep):
    from pipeline_lifecycle import identifier, verify_receipt
    identifier(operation_id)
    require(type(max_polls) is int and 1 <= max_polls <= 5760
            and type(poll_seconds) in (int, float) and 0 <= poll_seconds <= 300, "poll-bounds-invalid")
    reader = reader or ProviderReceiptReader(context)
    jobs = NativeJobs(context, transport=transport)
    for _ in range(max_polls):
        snapshot = reader.read_snapshot()
        _, root = snapshot._load(operation_id)
        require(root["plan_hash"] == plan_hash and root["plan"].get("provider_context") == context
                and root["status"] in ("succeeded", "continuation-required"),
                "observer-operation-binding-mismatch")
        proof_kind = "github-rs256-native-finalizer" if context["provider"] == "gha" else "ado-native-server-finalizer"
        proof = root.get("finalization", {}).get("proof", {})
        require(root.get("admission", {}).get("status") == "released"
                and root.get("finalization", {}).get("status") == "succeeded"
                and proof.get("operation_id") == operation_id and proof.get("plan_hash") == plan_hash
                and proof.get("proof_kind") == proof_kind, "observer-finalization-required")
        _scheduled_chain(snapshot, root, jobs)
        if root["status"] == "succeeded":
            receipt = {"operation_id": operation_id, "plan_hash": plan_hash,
                       "provider_context": context, "status": "succeeded"}
            result = verify_receipt(receipt, context, service=snapshot)
            current, ready = root, True
            while True:
                child_context = current["plan"].get("provider_context", {})
                require({key: value for key, value in child_context.items() if key not in ("run_id", "correlation_id")}
                        == {key: value for key, value in context.items() if key not in ("run_id", "correlation_id")}
                        and current["finalization"]["proof"]["proof_kind"] == proof_kind,
                        "observer-completion-binding-mismatch")
                jobs.not_failed(current)
                ready = jobs.terminal(current) and ready
                if not current.get("completion"):
                    break
                _, current = snapshot._load(current["completion"]["operation_id"])
            if ready:
                return result
        sleep(poll_seconds)
    raise DispatchError("scenario-completion-timeout-not-completed")
