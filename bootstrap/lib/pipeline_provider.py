"""Thin protected-job orchestration shared by the GHA and ADO pipeline copies."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID, uuid5

from pipeline_dispatch import DispatchError, dispatch_run, operation_selection, require


def invoke(command, output, *, expected, run=None, prepared=False):
    result = (run or subprocess.run)(command + ["--output", str(output)], check=False, shell=False)
    require(result.returncode in ((0,) if prepared else (0, 3)), "lifecycle-command-not-completed")
    value = json.loads(output.read_text(encoding="utf-8"))
    require(isinstance(value, dict) and all(value.get(key) == item for key, item in expected.items()),
            "lifecycle-result-binding-mismatch")
    status = "prepared" if prepared else ("succeeded" if result.returncode == 0 else "continuation-required")
    require(value.get("status") == status, "lifecycle-exit-status-mismatch")
    if result.returncode == 3:
        require(value.get("continuation") == {
            "command": "prepare-continuation", "requires_fresh_review": True,
            "operation_id": value["operation_id"], "plan_hash": value["plan_hash"]},
            "verified-continuation-required")
    return value


def wait_for_predecessor(operation_id, plan_hash, context, *, reader=None, transport=None,
                         max_polls=120, poll_seconds=15, sleep=time.sleep, recovery=False):
    """Continuation waits for its mutating finalizer; recovery waits for the old run."""
    from pipeline_dispatch import (
        GHA_WORKFLOW, ProviderReceiptReader, ProviderTransport, _ado_definition, _gha_identity, validate_binding,
    )
    from pipeline_lifecycle import identifier
    require(type(max_polls) is int and 1 <= max_polls <= 5760
            and type(poll_seconds) in (int, float) and 0 <= poll_seconds <= 300, "poll-bounds-invalid")
    _, parent = (reader or ProviderReceiptReader(context))._load(identifier(operation_id))
    predecessor = parent["plan"].get("provider_context", {})
    immutable = lambda value: {key: item for key, item in value.items() if key not in ("run_id", "correlation_id")}
    require(parent["plan_hash"] == plan_hash
            and parent["status"] in (("running", "cancel-pending", "reconciliation-required",
                                     "succeeded", "continuation-required") if recovery
                                    else ("continuation-required",))
            and immutable(predecessor) == immutable(context)
            and type(predecessor.get("run_id")) is int and predecessor["run_id"] > 0
            and predecessor["run_id"] != context.get("run_id")
            and type(predecessor.get("run_attempt")) is int and predecessor["run_attempt"] == 1,
            "continuation-predecessor-binding-mismatch")
    provider, run_id = context["provider"], predecessor["run_id"]
    if not recovery:
        proof = parent.get("finalization", {}).get("proof", {})
        require(parent.get("admission", {}).get("status") == "released"
                and parent.get("finalization", {}).get("status") == "succeeded"
                and proof.get("operation_id") == operation_id and proof.get("plan_hash") == plan_hash
                and proof.get("proof_kind") == ("github-rs256-native-finalizer" if provider == "gha"
                                               else "ado-native-server-finalizer"),
                "continuation-finalization-required")
        from pipeline_observer import NativeJobs
        jobs = NativeJobs(context, transport=transport)
        for _ in range(max_polls):
            if jobs.terminal(parent, finalizer_only=True):
                return
            sleep(poll_seconds)
        raise DispatchError("continuation-predecessor-finalizer-timeout")
    binding = {"schema": 1, "provider": provider, "repository": context["repository"],
               "consumer_commit": context["consumer_commit"]}
    base = validate_binding({"provider": provider}, binding)
    transport = transport or ProviderTransport(provider, base)
    workflow_id = None
    if provider == "gha":
        _, _, workflow = transport.request("GET", base + "/actions/workflows/pipelines-only-gha.yml")
        require(workflow.get("path") == GHA_WORKFLOW and workflow.get("state") == "active"
                and type(workflow.get("id")) is int, "fixed-provider-workflow-required")
        workflow_id = workflow["id"]
    for _ in range(max_polls):
        if provider == "gha":
            _, _, run = transport.request("GET", f"{base}/actions/runs/{run_id}")
            # Manual UI runs may leave the input blank; preflight then generates
            # the durable correlation without changing the enclosing run title.
            correlation = "" if run.get("display_title") == "pipelines-only []" else predecessor["correlation_id"]
            _gha_identity(run, binding=binding, workflow=workflow_id,
                          correlation=correlation, run_id=run_id)
            terminal = run.get("status") == "completed"
        else:
            _, _, run = transport.request("GET", f"{base}/build/builds/{run_id}?api-version=7.1")
            require(run.get("id") == run_id and run.get("sourceVersion") == context["consumer_commit"]
                    and run.get("sourceBranch") == parent["plan"]["origin"]["ref"]
                    and run.get("repository", {}).get("url", "").lower() == context["repository"].lower()
                    and run.get("repository", {}).get("type") == "TfsGit"
                    and type(run.get("definition", {}).get("id")) is int,
                    "provider-run-identity-mismatch")
            if workflow_id is None:
                workflow_id = _ado_definition(transport, base, dict(binding, pipeline_id=run["definition"]["id"]))
            require(run["definition"]["id"] == workflow_id, "provider-run-identity-mismatch")
            terminal = run.get("status") == "completed"
        if terminal:
            require(run.get("conclusion") in (
                "success", "failure", "cancelled", "timed_out", "neutral", "skipped", "action_required",
                "stale", "startup_failure") if provider == "gha" else
                run.get("result") in ("succeeded", "partiallySucceeded", "failed", "canceled"),
                "recovery-predecessor-result-unverified")
            return
        sleep(poll_seconds)
    raise DispatchError("recovery-predecessor-wait-timeout")


def schedule_continuation(service, operation_id, plan_hash, context, binding, *,
                          canonical=None, verify=None, launch=None):
    from pipeline_approvals import verify_finalizer
    from pipeline_lifecycle import identifier
    revision, parent = service._load(identifier(operation_id))
    require(parent["plan_hash"] == plan_hash and parent["plan"].get("provider_context") == context
            and parent["status"] == "continuation-required"
            and parent.get("admission", {}).get("status") == "released"
            and parent.get("finalization", {}).get("status") == "succeeded",
            "continuation-finalized-parent-required")
    require(not parent.get("provider_continuation"), "continuation-dispatch-already-claimed")
    seen, ancestor = {operation_id}, parent
    while ancestor["plan"].get("continuation_of"):
        relationship = ancestor["plan"]["continuation_of"]
        require(relationship["operation_id"] not in seen and len(seen) < 7, "continuation-chain-invalid")
        seen.add(relationship["operation_id"])
        _, ancestor = service._load(relationship["operation_id"])
        require(ancestor["plan_hash"] == relationship["plan_hash"], "continuation-parent-binding-mismatch")
    (verify or verify_finalizer)(parent)
    correlation = uuid5(UUID(operation_id), plan_hash + ":provider-continuation").hex
    parameters = {key: context[key] for key in
                  ("request_path", "request_digest", "consumer_commit", "source_commit")}
    parameters.update(correlation_id=correlation, parent_operation_id=operation_id, parent_plan_hash=plan_hash)
    parent["provider_continuation"] = {"status": "dispatching", "correlation_id": correlation}
    service._save(revision, copy.deepcopy(parent))
    run_id, _, _ = (launch or dispatch_run)(parameters, canonical or parent["snapshot"], binding)
    revision, parent = service._load(operation_id)
    require(parent.get("provider_continuation") == {"status": "dispatching", "correlation_id": correlation},
            "continuation-dispatch-claim-changed")
    parent["provider_continuation"] = {"status": "dispatched", "correlation_id": correlation, "run_id": run_id}
    service._save(revision, parent)
    return parent["provider_continuation"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute", "finalize", "complete"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-root", default="azure-enterprise-scale-ml")
    parser.add_argument("--request", required=True)
    parser.add_argument("--provider-context", required=True)
    parser.add_argument("--prepared")
    parser.add_argument("--output", required=True)
    parser.add_argument("--parent-operation-id", default="")
    parser.add_argument("--parent-plan-hash", default="")
    parser.add_argument("--recovery-operation-id", default="")
    parser.add_argument("--recovery-plan-hash", default="")
    parser.add_argument("--max-polls", type=int, default=1200)
    args = parser.parse_args(argv)
    try:
        from pipeline_inputs import read_json, resolve_request
        from pipeline_lifecycle import identifier
        selection = operation_selection(parent_operation_id=args.parent_operation_id, parent_plan_hash=args.parent_plan_hash,
                                        recovery_operation_id=args.recovery_operation_id,
                                        recovery_plan_hash=args.recovery_plan_hash)
        require(args.command == "prepare" or not selection, "operation-selection-is-prepare-only")
        root, source = Path(args.repo_root), Path(args.source_root)
        context = read_json(root, args.provider_context)
        command = [sys.executable, str(source / "bootstrap/lib/pipeline_lifecycle.py")]
        common = ["--repo-root", str(root), "--source-root", str(source), "--request", args.request,
                  "--provider-context", args.provider_context]
        output = root / args.output
        require(not output.exists() and not output.is_symlink()
                and output.resolve().is_relative_to(root.resolve()), "new-review-output-required")
        if args.command == "prepare":
            action = "prepare"
            prior_id = args.recovery_operation_id or args.parent_operation_id
            prior_hash = args.recovery_plan_hash or args.parent_plan_hash
            if selection:
                if args.recovery_operation_id:
                    wait_for_predecessor(prior_id, prior_hash, context, recovery=True)
                    action = "prepare-recovery"
                else:
                    wait_for_predecessor(prior_id, prior_hash, context)
                    action = "prepare-continuation"
                common += ["--operation-id", prior_id, "--expected-plan-hash", prior_hash]
            prepared = invoke(command + [action] + common, output, expected={"provider_context": context}, prepared=True)
            if selection:
                require(prepared["operation_id"] != prior_id, "new-reviewed-operation-required")
                relationship = "recovery_of" if args.recovery_operation_id else "continuation_of"
                prepared[relationship] = {"operation_id": prior_id, "plan_hash": prior_hash}
                output.write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
        elif args.command == "complete":
            from pipeline_observer import wait_for_completion
            require(bool(args.prepared) and context.get("request_path") == args.request,
                    "prepared-operation-required")
            prepared = read_json(root, args.prepared)
            require(prepared.get("provider_context") == context, "prepared-context-changed")
            result = wait_for_completion(identifier(prepared["operation_id"]), prepared["plan_hash"], context,
                                         max_polls=args.max_polls)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream)
            print(json.dumps(result))
        else:
            require(bool(args.prepared), "prepared-operation-required")
            prepared = read_json(root, args.prepared)
            expected = {key: prepared[key] for key in ("operation_id", "plan_hash", "provider_context")}
            require(expected["provider_context"] == context, "prepared-context-changed")
            common += ["--operation-id", identifier(prepared["operation_id"]),
                       "--expected-plan-hash", prepared["plan_hash"]]
            receipt = invoke(command + [args.command] + common, output, expected=expected)
            for relationship in ("continuation_of", "recovery_of"):
                if prepared.get(relationship) is not None:
                    receipt[relationship] = prepared[relationship]
            if args.command == "finalize" and receipt["status"] == "continuation-required":
                from pipeline_dispatch import operational_binding
                from pipeline_lifecycle_adapters import build_service
                canonical = resolve_request(root, read_json(root, args.request))
                service = build_service(canonical, repo_root=root, source_root=source,
                                        state_root=root / ".pipeline-lifecycle", provider_context=context)
                receipt["provider_continuation"] = schedule_continuation(
                    service, prepared["operation_id"], prepared["plan_hash"], context,
                    operational_binding(root, canonical), canonical=canonical)
            output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, DispatchError) as error:
        print(json.dumps({"status": "not-completed",
                          "error_code": getattr(error, "code", "provider-workflow-not-completed")}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
