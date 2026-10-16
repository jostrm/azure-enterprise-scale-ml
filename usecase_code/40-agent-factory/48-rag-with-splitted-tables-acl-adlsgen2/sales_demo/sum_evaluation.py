"""Offline, post-inference evaluation; never imported by model invocation code."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import json
import re

from .arithmetic import validate_row
from .configuration import digest, local_file, read_json

_INTEGER = r"(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)"
_SALE_ID = re.compile(r"SALE-\d{6}\Z")
_HEADERS = {
    "source": {"source", "partition"},
    "first_id": {"first sale id", "first id"},
    "last_id": {"last sale id", "last id"},
    "count": {"records", "record count", "deduplicated record count", "deduplicated readable records"},
    "minor": {"net subtotal (cents)", "net subtotal (usd cents)", "subtotal (cents)",
              "net total (cents)", "net total (usd cents)", "net sales (cents)"},
    "usd": {"usd", "net total (usd)", "net subtotal (usd)", "total (usd)"},
}


def load_expected(config, oracle_path):
    """Validate fixture integrity and independently compute Decimal expectations."""
    oracle = read_json(Path(oracle_path))
    if (config["dataset"] != "car-sales" or oracle.get("dataset") != config["dataset"]
            or oracle.get("version") != config["version"] or oracle.get("currency") != "USD"):
        raise ValueError("Oracle does not match the selected synthetic dataset/version.")
    root = Path(config["artifacts_root"])
    partitions, all_ids = {}, set()
    for part in config["partitions"]:
        source = part["id"]
        if source not in {"json", "excel"} or source in partitions:
            raise ValueError("Scoring requires exactly the two primary disjoint partitions.")
        raw = local_file(root / "master", part["rows_path"]).read_bytes()
        if (digest(raw) != part["rows_sha256"]
                or raw != local_file(root / "project", part["rows_path"]).read_bytes()):
            raise ValueError("Authoritative row bytes differ from the pinned master/project publication.")
        amounts = {}
        for line in raw.decode("utf-8").splitlines():
            row = json.loads(line)
            validate_row(row, config["dataset"], config["version"])
            key = row["sale_id"]
            if not _SALE_ID.fullmatch(key) or key in all_ids:
                raise ValueError("Primary fixture sale IDs must be canonical, unique and disjoint.")
            all_ids.add(key)
            amount = Decimal(0) if row["status"] == "cancelled" else (
                Decimal(row["quantity"]) * Decimal(row["unit_price_minor"])
                - Decimal(row["discount_minor"]) - Decimal(row["refund_minor"])
            )
            amounts[key] = int(amount)
        ids = sorted(amounts)
        if (len(ids) != part["row_count"]
                or digest(("\n".join(ids) + "\n").encode()) != part["sale_ids_sha256"]):
            raise ValueError("Source row count or sale-ID hash differs from the manifest.")
        expected = oracle.get("partitions", {}).get(source, {})
        if (any(expected.get(field) != part[field] for field in ("row_count", "rows_sha256", "sale_ids_sha256"))
                or expected.get("sale_ids") != ids):
            raise ValueError("Oracle source identities do not match the pinned publication.")
        subtotal = sum(amounts.values())
        if type(oracle.get("source_subtotals_minor", {}).get(source)) is not int or oracle["source_subtotals_minor"][source] != subtotal:
            raise ValueError("Oracle subtotal differs from independent Decimal computation.")
        partitions[source] = {"amounts": amounts, "total_minor": subtotal,
                              "input_sha256": part["input_sha256"]}
    total = sum(part["total_minor"] for part in partitions.values())
    if (set(partitions) != {"json", "excel"}
            or set(oracle.get("source_subtotals_minor", {})) != set(partitions)
            or any(type(oracle.get(key)) is not int or oracle[key] != value
                   for key, value in (("total_minor", total), ("unique_row_count", len(all_ids)),
                                      ("input_row_count", len(all_ids))))):
        raise ValueError("Oracle complete-dataset count or total is inconsistent.")
    return {"dataset": config["dataset"], "version": config["version"], "partitions": partitions,
            "total_minor": total, "row_count": len(all_ids)}


def _clean(cell):
    return cell.strip().replace("**", "").replace("`", "").strip()


def _integer(value):
    if not re.fullmatch(_INTEGER, value, flags=re.ASCII):
        raise ValueError("Expected a nonnegative integer with optional standard thousands separators.")
    return int(value.replace(",", ""))


def _dollars_minor(value):
    if not re.fullmatch(r"\$?" + _INTEGER + r"\.\d{2}", value, flags=re.ASCII):
        raise ValueError("Expected USD with exactly two decimal places.")
    return int(Decimal(value.removeprefix("$").replace(",", "")) * 100)


def _tables(text, failures):
    table, header, fenced = None, None, False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            table = header = None
            continue
        if fenced:
            continue
        if not line.strip().startswith("|"):
            table = header = None
            continue
        cells = [_clean(cell) for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            if header is None:
                failures.append(f"unsupported-table-header:line-{number}")
            else:
                table = header
            continue
        roles = [next((role for role, aliases in _HEADERS.items() if cell.lower() in aliases), None)
                 for cell in cells]
        if "source" in roles and "count" in roles:
            wanted = {"source", "first_id", "last_id", "count", "minor"} if "first_id" in roles else {"source", "count", "minor", "usd"}
            header = roles if len(roles) == len(wanted) and set(roles) == wanted else None
            table = None
            if header is None:
                failures.append(f"unsupported-table-header:line-{number}")
            continue
        if table is None or len(cells) != len(table):
            failures.append(f"unsupported-table-row:line-{number}")
            continue
        yield number, dict(zip(table, cells))


def _response(value, failures):
    raw = value.get("output")
    if "output" in value and not isinstance(raw, list):
        failures.append("invalid-output-array")
    if isinstance(raw, list):
        if any(not isinstance(item, dict) for item in raw):
            failures.append("invalid-output-item")
            raw = [item for item in raw if isinstance(item, dict)]
        types = [item.get("type") for item in raw]
        texts = []
        for message in raw:
            if message.get("type") != "message" or message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                failures.append("invalid-message-content")
                continue
            for item in content:
                if not isinstance(item, dict):
                    failures.append("invalid-message-content")
                elif item.get("type") == "output_text" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
        text = "\n".join(texts)
        calls = [item for item in raw if item.get("type") == "mcp_call"]
        if isinstance(value.get("text"), str) and value["text"] != text:
            failures.append("raw-and-summary-answer-disagree")
    else:
        text = value.get("text")
        types = value.get("output_types", [])
        calls = value.get("retrieval_calls", [])
    if value.get("status") != "completed":
        failures.append("response-not-completed-or-status-missing")
    if not isinstance(text, str) or not text.strip():
        failures.append("missing-answer")
        text = ""
    if (not isinstance(types, list) or "message" not in types
            or any(not isinstance(kind, str) or kind not in {"message", "reasoning", "mcp_call", "mcp_list_tools"} for kind in types)):
        failures.append("missing-or-disallowed-output-types")
    if not isinstance(calls, list):
        failures.append("invalid-tool-trace")
        calls = []
    for call in calls:
        if (not isinstance(call, dict) or call.get("name") != "knowledge_base_retrieve"
                or call.get("error") or not call.get("output")):
            failures.append("failed-or-disallowed-tool")
    if isinstance(types, list) and types.count("mcp_call") != len(calls):
        failures.append("incomplete-tool-trace")
    if value.get("calculator_used") is True or value.get("oracle_supplied") is True:
        failures.append("calculator-or-oracle-used")
    return text


def score_response(response, expected):
    """Score a local response's reported audit, not the model's hidden reasoning."""
    if not isinstance(response, dict):
        raise ValueError("Response must be a JSON object.")
    failures = []
    text = _response(response, failures)
    partitions = expected["partitions"]
    if "sources" in response:
        sources = response["sources"]
        if (not isinstance(sources, list) or len(sources) != len(partitions)
                or any(not isinstance(item, dict) for item in sources)
                or {item.get("source") for item in sources} != set(partitions)
                or any(item.get("content_sha256") != partitions[item["source"]]["input_sha256"] for item in sources)):
            failures.append("source-binding-mismatch")
    groups, totals, seen = [], {}, Counter()
    for number, row in _tables(text, failures):
        source = row["source"].lower()
        if source not in partitions and not ("first_id" not in row and source == "combined"):
            failures.append(f"unknown-source:line-{number}")
            continue
        try:
            count, amount = _integer(row["count"]), _integer(row["minor"])
            dollars = _dollars_minor(row["usd"]) if "usd" in row else None
        except ValueError as error:
            failures.append(f"invalid-number:line-{number}:{error}")
            continue
        if "first_id" in row:
            first, last = row["first_id"], row["last_id"]
            amounts = partitions[source]["amounts"]
            if first not in amounts or last not in amounts or first > last:
                failures.append(f"invalid-range:line-{number}")
                continue
            ids = [key for key in sorted(amounts) if first <= key <= last]
            seen.update((source, key) for key in ids)
            expected_amount = sum(amounts[key] for key in ids)
            matches = count == len(ids) and 1 <= count <= 20 and amount == expected_amount
            groups.append({"source": source, "first_id": first, "last_id": last,
                           "reported_count": count, "expected_count": len(ids),
                           "reported_minor": amount, "expected_minor": expected_amount,
                           "difference_minor": amount - expected_amount, "matches": matches})
            if not matches:
                failures.append(f"audit-group-mismatch:line-{number}")
        else:
            if source in totals:
                failures.append(f"duplicate-total:{source}")
                continue
            expected_count = expected["row_count"] if source == "combined" else len(partitions[source]["amounts"])
            expected_amount = expected["total_minor"] if source == "combined" else partitions[source]["total_minor"]
            matches = count == expected_count and amount == dollars == expected_amount
            totals[source] = {"reported_count": count, "expected_count": expected_count,
                              "reported_minor": amount, "reported_usd_minor": dollars,
                              "expected_minor": expected_amount, "matches": matches}
            if not matches:
                failures.append(f"total-mismatch:{source}")
    all_ids = {(source, key) for source, part in partitions.items() for key in part["amounts"]}
    missing = sorted(all_ids - set(seen))
    duplicates = sorted(key for key, count in seen.items() if count != 1)
    coverage = "unverifiable" if not groups else "incomplete" if missing or duplicates else "complete"
    if coverage != "complete":
        failures.append("audit-coverage-" + coverage)
    total_status = ("unverifiable" if not totals or any(item.startswith("duplicate-total:") for item in failures) else "correct"
                    if set(totals) == {*partitions, "combined"} and all(item["matches"] for item in totals.values())
                    else "incorrect")
    if total_status != "correct":
        failures.append("totals-" + total_status)
    return {
        "passed": not failures, "mode": "offline-post-inference", "live_execution_verified": False,
        "dataset": expected["dataset"], "version": expected["version"],
        "response_id": response.get("response_id", response.get("id")),
        "totals": {"status": total_status, "sources": totals},
        "coverage": {"status": coverage, "unique_rows": len(seen), "expected_rows": expected["row_count"],
                     "missing_ids": [{"source": source, "sale_id": key} for source, key in missing],
                     "duplicate_ids": [{"source": source, "sale_id": key} for source, key in duplicates]},
        "groups": groups, "failures": list(dict.fromkeys(failures)),
        "boundary": "Scores the reported audit, not hidden model reasoning or authenticated live execution; never send this report to the model.",
    }
