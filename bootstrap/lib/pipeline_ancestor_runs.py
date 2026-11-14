"""Read-only proof of finalized continuation ancestors, never an ignore-run list.

``state`` must come from an authenticated ProviderState.read(), not origin JSON.
``request`` has the native state_request(kind, method, endpoint, body, allowed)
signature. Both entry points perform fresh provider reads and never mutate state.
"""

import hashlib
import re
from urllib.parse import quote, unquote, urlsplit

from lifecycle_admission import RECORD, PROTOCOL
from pipeline_lifecycle import PipelineError, bound_plan, digest, identifier, require


ORIGIN_FIELDS = ("provider", "repository", "run_id", "attempt", "commit", "ref")


def _record(record):
    require(isinstance(record, dict) and record.get("schema") == 1, "ancestor-operation-required")
    identifier(record.get("operation_id"))
    require(digest(record["snapshot"]) == record["snapshot_hash"]
            and digest(bound_plan(record)) == record["plan_hash"], "ancestor-operation-binding-mismatch")
    return record


def _origin(origin):
    require(isinstance(origin, dict) and origin.get("provider") in ("gha", "ado")
            and type(origin.get("attempt")) is int and origin["attempt"] == 1
            and isinstance(origin.get("run_id"), str) and re.fullmatch(r"[1-9][0-9]*", origin["run_id"])
            and isinstance(origin.get("commit"), str) and re.fullmatch(r"[a-f0-9]{40}", origin["commit"])
            and isinstance(origin.get("ref"), str) and re.fullmatch(r"refs/heads/[A-Za-z0-9_./-]+", origin["ref"]),
            "ancestor-origin-invalid")
    return {key: origin[key] for key in ORIGIN_FIELDS}


def _get(request, provider, path):
    status, headers, body = request(provider, "GET", path, None, (200,))
    require(status == 200 and isinstance(body, dict)
            and not any(key.lower() in ("link", "x-ms-continuationtoken") for key in headers),
            "complete-ancestor-provider-evidence-required")
    return body


def _released(record, state):
    from pipeline_approvals import ENVIRONMENT, TEMPLATES
    origin = _origin(record["plan"]["origin"])
    repository = "https://github.com/" + origin["repository"] if origin["provider"] == "gha" else origin["repository"]
    require(state.get("repository") == repository, "ancestor-repository-mismatch")
    proof = record.get("finalization", {}).get("proof", {})
    expected_hash = hashlib.sha256((TEMPLATES / f"pipelines-only-{origin['provider']}.yml")
                                  .read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    require(record.get("status") == "continuation-required"
            and record.get("admission", {}).get("status") == "released"
            and record.get("finalization", {}).get("status") == "succeeded"
            and all(proof.get(key) == value for key, value in origin.items())
            and proof.get("operation_id") == record["operation_id"] and proof.get("plan_hash") == record["plan_hash"]
            and proof.get("environment") == ENVIRONMENT and proof.get("workflow_sha256") == expected_hash
            and proof.get("proof_kind") == ("github-rs256-native-finalizer" if origin["provider"] == "gha"
                                           else "ado-native-server-finalizer"), "ancestor-native-finalization-required")
    claim = record.get("admission_claim", {})
    outer = state["records"].get(RECORD, {})
    history = outer.get("history", {}).get(claim.get("id"), {})
    observation = history.get("observation", {})
    stages = record["plan"].get("stages", [])
    native_runs = {manifest["run_id"] for stage in stages for manifest in stage.get("manifests", [])}
    native_plans = {stage["native_review"]["plan_hash"] for stage in stages if "native_review" in stage}
    active = state.get("active") or {}
    require(claim.get("protocol") == PROTOCOL and claim.get("route") == "pipeline"
            and claim.get("operation_id") == record["operation_id"] and claim.get("review_digest") == record["plan_hash"]
            and claim.get("identity", {}).get("run_id") == origin["run_id"]
            and claim.get("identity", {}).get("repository") == repository
            and history.get("claim") == claim
            and (outer.get("claim") or {}).get("operation_id") != record["operation_id"]
            and active.get("run_id") not in native_runs and active.get("plan_hash") not in native_plans
            and active.get("operation_id") != record["operation_id"]
            and observation.get("run_id") == origin["run_id"] and observation.get("repository") == repository
            and observation.get("terminal") is True and observation.get("inventory_complete") is True
            and observation.get("active_operations") == [] and observation.get("evidence_id"),
            "ancestor-native-release-required")
    return origin, proof


def _github(record, origin, proof, request):
    base = "repos/" + origin["repository"] + "/actions/runs/" + origin["run_id"]
    run = _get(request, "gha", base)
    require(str(run.get("id")) == origin["run_id"] and run.get("run_attempt") == 1
            and run.get("head_sha") == origin["commit"] and "refs/heads/" + run.get("head_branch", "") == origin["ref"]
            and run.get("repository", {}).get("full_name") == origin["repository"]
            and run.get("event") == "workflow_dispatch" and run.get("path") == ".github/workflows/pipelines-only-gha.yml"
            and (run.get("status") == "in_progress" and run.get("conclusion") is None
                 or run.get("status") == "completed" and run.get("conclusion") == "success"),
            "ancestor-provider-run-mismatch")
    page = _get(request, "gha", base + "/jobs?filter=latest&per_page=100")
    jobs = page.get("jobs")
    require(isinstance(jobs, list) and type(page.get("total_count")) is int
            and len(jobs) == page["total_count"] == 4, "complete-ancestor-job-inventory-required")
    names = ("prepare", f"Execute reviewed {record['operation_id']} / {record['plan_hash']}",
             f"Finalize reviewed {record['operation_id']} / {record['plan_hash']}", "complete")
    require({job.get("name") for job in jobs} == set(names)
            and len({job.get("id") for job in jobs}) == 4, "ancestor-jobs-mismatch")
    by_name = {job["name"]: job for job in jobs}
    for job in jobs:
        require(str(job.get("run_id")) == origin["run_id"] and job.get("run_attempt") == 1
                and job.get("head_sha") == origin["commit"], "ancestor-job-source-mismatch")
        if job["name"] != "complete":
            require(job.get("status") == "completed" and job.get("conclusion") == "success",
                    "ancestor-mutating-job-not-succeeded")
    require(by_name[names[1]]["id"] == proof.get("execution_job_id")
            and by_name[names[2]]["id"] == proof.get("job_id") and proof.get("execution_result") == "success",
            "ancestor-finalizer-job-mismatch")
    waiter = by_name["complete"]
    require("self-hosted" not in waiter.get("labels", [])
            and (run["status"] != "completed" or waiter.get("status") == "completed")
            and (waiter.get("status") in ("queued", "in_progress") and waiter.get("conclusion") is None
                 or waiter.get("status") == "completed" and waiter.get("conclusion") == "success"),
            "ancestor-readonly-completion-required")
    return run


def _ado(record, origin, proof, request):
    org, project, _, _ = unquote(urlsplit(origin["repository"]).path).strip("/").split("/")
    base = "https://dev.azure.com/" + quote(org, safe="") + "/" + quote(project, safe="") + "/_apis"
    run_path = base + "/build/builds/" + origin["run_id"]
    run = _get(request, "ado", run_path + "?api-version=7.1")
    require(str(run.get("id")) == origin["run_id"] and run.get("sourceVersion") == origin["commit"]
            and run.get("sourceBranch") == origin["ref"] and run.get("repository", {}).get("url") == origin["repository"]
            and run.get("repository", {}).get("type") == "TfsGit"
            and (run.get("status") == "inProgress" and run.get("result") is None
                 or run.get("status") == "completed" and run.get("result") == "succeeded"),
            "ancestor-provider-run-mismatch")
    definition = run.get("definition", {})
    require(type(definition.get("id")) is int and type(definition.get("revision")) is int,
            "ancestor-immutable-definition-required")
    installed = _get(request, "ado", base + f"/build/definitions/{definition['id']}?revision={definition['revision']}&api-version=7.1")
    require(installed.get("id") == definition["id"] and installed.get("revision") == definition["revision"]
            and installed.get("repository", {}).get("id") == run["repository"].get("id")
            and installed.get("process", {}).get("yamlFilename", "").lstrip("/") == "pipelines-only-ado.yml",
            "ancestor-installed-pipeline-mismatch")
    rows = _get(request, "ado", run_path + "/timeline?api-version=7.1").get("records")
    require(isinstance(rows, list) and rows, "ancestor-timeline-required")
    by_id = {row["id"]: row for row in rows}
    require(len(by_id) == len(rows), "ancestor-ambiguous-timeline")
    expected = {"PrepareOperation": "Prepare", "ReviewPipelinesLifecycle": "Review",
                "ExecuteReviewedOperation": "Execute", "FinalizeReviewedOperation": "Finalize",
                "ObserveScenarioCompletion": "Complete"}
    stages = [row for row in rows if row.get("type") == "Stage"]
    jobs = [row for row in rows if row.get("type") == "Job"]
    require(len(stages) == len(jobs) == 5 and {row.get("name") for row in stages} == set(expected.values())
            and {row.get("identifier") for row in jobs} == set(expected), "ancestor-jobs-mismatch")
    for row in rows:
        require(row.get("attempt", 1) == 1 and not row.get("previousAttempts"), "ancestor-rerun-forbidden")
        root, seen = row, set()
        while root.get("parentId"):
            require(root["id"] not in seen and root["parentId"] in by_id, "ancestor-timeline-ancestry-invalid")
            seen.add(root["id"])
            root = by_id[root["parentId"]]
        require(root.get("type") == "Stage", "ancestor-timeline-ancestry-invalid")
        if row.get("type") == "Job":
            require(root["name"] == expected[row["identifier"]], "ancestor-job-stage-mismatch")
        if root.get("name") != "Complete":
            require(row.get("state") == "completed" and row.get("result") == "succeeded",
                    "ancestor-mutating-job-not-succeeded")
        else:
            require((run["status"] != "completed" or row.get("state") == "completed")
                    and (row.get("state") in ("pending", "inProgress") and row.get("result") is None
                         or row.get("state") == "completed" and row.get("result") == "succeeded"),
                    "ancestor-readonly-completion-required")
    by_name = {row["identifier"]: row for row in jobs}
    require(by_name["FinalizeReviewedOperation"]["id"] == proof.get("job_id")
            and by_name["ExecuteReviewedOperation"]["id"] == proof.get("execution_job_id")
            and proof.get("execution_result") == "succeeded", "ancestor-finalizer-job-mismatch")
    return run


def assert_finalized_run(record, *, state, request):
    """Prove native finalization/release and terminal-success mutating provider jobs.

    The only permitted live work is the fixed hosted Complete waiter. This also
    accepts an entirely successful terminal workflow; never failed/cancelled runs.
    """
    try:
        _record(record)
        require(state.get("records", {}).get("pipeline-lifecycle/" + record["operation_id"] + ".json") == record,
                "ancestor-durable-record-required")
        origin, proof = _released(record, state)
        return (_github if origin["provider"] == "gha" else _ado)(record, origin, proof, request)
    except (KeyError, TypeError, AttributeError, OSError):
        raise PipelineError("ancestor-evidence-invalid") from None


def quiescent_ancestors(origin, *, state, request):
    """Return verified ancestor run IDs; origin-supplied parent hints are ignored."""
    try:
        current = _origin(origin)
        require(isinstance(state, dict) and isinstance(state.get("records"), dict), "ancestor-state-required")
        operations = {key.removeprefix("pipeline-lifecycle/").removesuffix(".json"): value
                      for key, value in state["records"].items()
                      if re.fullmatch(r"pipeline-lifecycle/[a-f0-9-]{36}\.json", key)}
        matches = [value for value in operations.values()
                   if isinstance(value, dict) and value.get("plan", {}).get("origin") == origin]
        require(len(matches) <= 1, "ancestor-current-operation-ambiguous")
        child = _record(matches[0]) if matches else None
        ancestors, seen = set(), {current["run_id"]}
        for _ in range(32):
            relation = child["plan"].get("continuation_of") if child else None
            if child is not None:
                if not relation:
                    return ancestors
                parent = _record(operations.get(relation["operation_id"]))
                require(parent["plan_hash"] == relation["plan_hash"]
                        and parent.get("continuation_child") == child["operation_id"]
                        and parent["snapshot"]["factory"]["id"] == child["snapshot"]["factory"]["id"],
                        "ancestor-continuation-binding-mismatch")
            else:
                matches = [value for value in operations.values() if isinstance(value, dict)
                           and value.get("provider_continuation", {}).get("status") == "dispatched"
                           and str(value["provider_continuation"].get("run_id")) == current["run_id"]]
                require(len(matches) <= 1, "ancestor-dispatch-ambiguous")
                if not matches:
                    return ancestors
                parent = _record(matches[0])
            parent_origin = _origin(parent["plan"]["origin"])
            require(all(parent_origin[key] == current[key] for key in ORIGIN_FIELDS if key != "run_id")
                    and parent_origin["run_id"] not in seen
                    and parent.get("provider_continuation", {}).get("status") == "dispatched"
                    and str(parent["provider_continuation"].get("run_id")) == current["run_id"],
                    "ancestor-dispatch-binding-mismatch")
            assert_finalized_run(parent, state=state, request=request)
            seen.add(parent_origin["run_id"])
            ancestors.add(parent_origin["run_id"])
            child, current = parent, parent_origin
        raise PipelineError("ancestor-chain-limit")
    except (KeyError, TypeError, AttributeError):
        raise PipelineError("ancestor-evidence-invalid") from None
