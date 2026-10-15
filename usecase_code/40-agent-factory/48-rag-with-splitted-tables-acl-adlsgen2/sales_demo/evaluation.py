"""Opt-in live evaluation. The independent oracle is loaded ONLY in this module."""
from __future__ import annotations

import json
from pathlib import Path

from .agent import invoke_agent, parse_reported_total
from .identity import SalesUnavailable

PROMPTS = (
    ("Give me the sum of all sales.", "all"),
    ("Give me the sum of sales in the JSON dataset.", "json"),
    ("Give me the sum of sales in the Excel workbook.", "excel"),
    ("Give me the total and break it down by source.", "all"),
)
BOTH_INDEX_PROMPT = (
    "Use retrieve_sales to show evidence from both authorized source indexes, with citations. "
    "Use aggregate_sales for the exact all-sales total and explain why top-k retrieval is not arithmetic."
)


def evaluate_result(result: dict, expected_minor: int, *, source: str,
                    expected_indexes: set[str] | None = None) -> dict:
    """Pure offline scoring is not a claim that the result came from Azure."""
    reasons = []
    try:
        reported = parse_reported_total(result["generated_text"])
        if reported != expected_minor:
            reasons.append("generated-number-mismatch")
    except (KeyError, ValueError, TypeError):
        reported = None
        reasons.append("missing-or-ambiguous-numeric-answer")
    authoritative = [r for r in result.get("authoritative", []) if r.get("scope") == source]
    if len(authoritative) != 1 or authoritative[0].get("total_minor") != expected_minor:
        reasons.append("calculator-number-mismatch")
    calls = [t for t in result.get("trace", [])
             if t.get("tool") == "aggregate_sales" and t.get("arguments") == {"source": source}]
    if len(calls) != 1:
        reasons.append("missing-exact-calculator-trace")
    else:
        indexes = calls[0].get("indexes", [])
        if expected_indexes is not None and set(indexes) != expected_indexes:
            reasons.append("index-coverage-mismatch")
        if len(indexes) != len(set(indexes)) or (source == "all" and expected_indexes is None and len(indexes) != 2):
            reasons.append("index-coverage-mismatch")
    return {"passed": not reasons, "reported_minor": reported, "expected_minor": expected_minor,
            "failures": reasons}


def _oracle(path: Path, config: dict) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if (value.get("dataset") != config["dataset"] or value.get("version") != config["version"]
            or value.get("currency") != "USD" or type(value.get("total_minor")) is not int
            or set(value.get("source_subtotals_minor", {})) != {"json", "excel"}
            or any(type(v) is not int for v in value["source_subtotals_minor"].values())):
        raise ValueError("Independent oracle does not match the selected publication.")
    for partition in config["partitions"]:
        expected = value["partitions"][partition["id"]]
        if any(expected.get(key) != partition[key] for key in ("rows_sha256", "sale_ids_sha256", "row_count")):
            raise ValueError("Independent oracle integrity does not match the selected publication.")
    return value


def evaluate_live(project, runtime, deployment: dict, oracle_path: Path, *,
                  allow_paid: bool = False, restricted_runtime=None,
                  restricted_deployment: dict | None = None,
                  restricted_project=None) -> dict:
    """Use separately authenticated runtimes; never substitute model/mock responses.

    A missing second principal blocks the ACL acceptance gate. Configure the
    restricted principal through a separate trusted CLI credential invocation,
    not by supplying oid/group/token values as model arguments.
    """
    if allow_paid is not True:
        raise ValueError("Live evaluation requires --allow-paid.")
    expected = _oracle(oracle_path, runtime.config)
    outcomes = []
    for prompt, source in PROMPTS:
        try:
            result = invoke_agent(project, runtime, prompt, deployment=deployment, allow_paid=True)
            total = expected["total_minor"] if source == "all" else expected["source_subtotals_minor"][source]
            score = evaluate_result(result, total, source=source)
            if "break it down" in prompt:
                records = result.get("authoritative", [])
                if not records or records[0].get("source_subtotals_minor") != expected["source_subtotals_minor"]:
                    score["passed"] = False
                    score["failures"].append("source-breakdown-mismatch")
            outcomes.append({"prompt": prompt, **score, "response": result})
        except SalesUnavailable:
            outcomes.append({"prompt": prompt, "passed": False, "failures": ["unavailable"]})
    try:
        evidence = invoke_agent(project, runtime, BOTH_INDEX_PROMPT, deployment=deployment, allow_paid=True)
        retrieval = [t for t in evidence["trace"] if t.get("tool") == "retrieve_sales"]
        indexes = {index for t in retrieval for index in t.get("indexes", [])}
        covered = {doc["partition"] for t in retrieval for doc in t.get("result", {}).get("evidence", [])}
        evidence_passed = len(indexes) == 2 and covered == {"json", "excel"}
        outcomes.append({"prompt": BOTH_INDEX_PROMPT, "passed": evidence_passed, "response": evidence})
    except SalesUnavailable:
        outcomes.append({"prompt": BOTH_INDEX_PROMPT, "passed": False, "failures": ["unavailable"]})
    restricted = {"state": "blocked", "reason": "A separately authenticated restricted principal is required."}
    if restricted_runtime is not None and restricted_deployment is not None and restricted_project is not None:
        try:
            full_identity = runtime.authorization.authorize()
            other = restricted_runtime.authorization.authorize()
            if full_identity.oid == other.oid or full_identity.tenant_id != other.tenant_id:
                raise SalesUnavailable()
            permitted = [
                p for p in restricted_runtime.config["partitions"]
                if other.oid in p.get("allowed_user_ids", []) or other.group_ids.intersection(p.get("allowed_group_ids", []))
            ]
            if len(permitted) != 1:
                raise SalesUnavailable()
            source = permitted[0]["id"]
            result = invoke_agent(
                restricted_project, restricted_runtime, PROMPTS[0][0],
                deployment=restricted_deployment, allow_paid=True,
            )
            indexes = {p["index"] for p in result["authoritative"][0]["provenance"]}
            score = evaluate_result(result, expected["source_subtotals_minor"][source],
                                    source="all", expected_indexes=indexes)
            # Local policy denial is not proof of native ACL enforcement: the Search
            # adapter separately attempts denied partition enumeration with this user.
            search_denied = restricted_runtime.search.verify_native_denial(other, allowed_partition=source)
            storage_denied = restricted_runtime.store.verify_native_denial(other, allowed_partition=source)
            if search_denied is not True or storage_denied is not True:
                score["passed"] = False
                score["failures"].append("native-denial-not-verified")
            denied_source = "excel" if source == "json" else "json"
            try:
                restricted_runtime.aggregate_sales(denied_source)
                score["passed"] = False
                score["failures"].append("denied-source-returned-data")
            except SalesUnavailable:
                pass
            restricted = {"state": "passed" if score["passed"] else "failed", **score, "response": result}
        except (SalesUnavailable, AttributeError, KeyError):
            restricted = {"state": "blocked", "reason": "Separate-principal native ACL evidence is incomplete."}
    passed = all(item["passed"] for item in outcomes) and restricted["state"] == "passed"
    return {"state": "passed" if passed else "blocked" if restricted["state"] == "blocked" else "failed",
            "live": True, "scope": "protected-sales-agent", "passed": passed,
            "cases": outcomes, "restricted_identity": restricted,
            "image_serving": "Separate isolated branch acceptance required.",
            "live_fault_injection": "Not exercised by this evaluation; offline failure cases are separate.",
            "acceptance": "Unit stubs are not live service evidence; all gates must pass."}
