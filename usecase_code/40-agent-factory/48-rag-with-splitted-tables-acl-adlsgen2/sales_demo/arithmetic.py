"""Strict integer arithmetic for authoritative sales rows, never RAG snippets."""

from datetime import date
import re


INTEGER_FIELDS = ("quantity", "unit_price_minor", "discount_minor", "refund_minor", "tax_minor")
STRING_FIELDS = ("dataset", "version", "sale_id", "dealership", "date", "car_model", "status")
STATUSES = frozenset({"completed", "refunded", "cancelled"})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def format_minor(value: int) -> str:
    if type(value) is not int:
        raise ValueError("A minor-unit amount must be an integer.")
    whole, cents = divmod(abs(value), 100)
    return f"{'-' if value < 0 else ''}{whole}.{cents:02d}"


def validate_row(row: dict, dataset: str, version: str) -> None:
    """Reject malformed rows or a different dataset/version; do not coerce values."""
    if not isinstance(row, dict):
        raise ValueError("sale row must be a dictionary")
    for name in STRING_FIELDS:
        value = row.get(name)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"{name} must be a nonempty, trimmed string")
    for name in ("dataset", "version"):
        if not IDENTIFIER.fullmatch(row[name]):
            raise ValueError(f"{name} must be a safe dataset/version identifier")
    if re.search(r"[\x00-\x1f\x7f]", row["sale_id"]):
        raise ValueError("sale_id must not contain line or control separators")
    if row["dataset"] != dataset or row["version"] != version:
        raise ValueError("dataset/version does not match the requested publication")
    if row.get("currency", "USD") != "USD":
        raise ValueError("currency must be USD")
    if row["status"] not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]):
        raise ValueError("date must be canonical YYYY-MM-DD")
    try:
        date.fromisoformat(row["date"])
    except ValueError as exc:
        raise ValueError("date must be a valid calendar date") from exc
    for name in INTEGER_FIELDS:
        value = row.get(name)
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer (not bool or float)")
    gross = row["quantity"] * row["unit_price_minor"]
    if row["discount_minor"] > gross:
        raise ValueError("discount_minor exceeds quantity * unit_price_minor")
    if row["refund_minor"] > gross - row["discount_minor"]:
        raise ValueError("refund_minor exceeds the discounted pretax amount")


def row_sales_minor(row: dict) -> int:
    """Net pretax USD cents: quantity * unit price - discount - refund; cancelled=0."""
    if not isinstance(row, dict):
        raise ValueError("sale row must be a dictionary")
    validate_row(row, row.get("dataset"), row.get("version"))
    if row["status"] == "cancelled":
        return 0
    return row["quantity"] * row["unit_price_minor"] - row["discount_minor"] - row["refund_minor"]


def aggregate_records(partition_rows: dict[str, list[dict]]) -> dict:
    """Deduplicate by business key, rejecting conflicts and same-partition duplicates.

    An identical cross-partition record belongs to the lexicographically first
    partition ID. Attribution is independent of input order and includes zero
    subtotals for completely overlapping or empty partitions.
    """
    if not isinstance(partition_rows, dict):
        raise ValueError("partition_rows must be a dictionary of lists")
    for source, rows in partition_rows.items():
        if not isinstance(source, str) or not source.strip() or source != source.strip():
            raise ValueError("partition IDs must be nonempty, trimmed strings")
        if not isinstance(rows, list):
            raise ValueError(f"partition {source!r} must contain a list of rows")
    seen: dict[tuple[str, str, str], dict] = {}
    subtotals = {source: 0 for source in sorted(partition_rows)}
    input_count = 0
    for source in subtotals:
        local_keys = set()
        for row in partition_rows[source]:
            amount = row_sales_minor(row)
            input_count += 1
            key = (row["dataset"], row["version"], row["sale_id"])
            if key in local_keys:
                raise ValueError(f"duplicate sale key within partition {source!r}: {key!r}")
            local_keys.add(key)
            if key in seen:
                if row != seen[key]:
                    raise ValueError(f"conflicting rows for sale key {key!r}")
                continue
            seen[key] = row
            subtotals[source] += amount
    return {
        "currency": "USD",
        "total_minor": sum(subtotals.values()),
        "total_decimal": format_minor(sum(subtotals.values())),
        "source_subtotals_minor": subtotals,
        "source_subtotals_decimal": {source: format_minor(amount) for source, amount in subtotals.items()},
        "input_row_count": input_count,
        "unique_row_count": len(seen),
        "duplicate_count": input_count - len(seen),
        "sales_definition": "net pretax: quantity * unit_price_minor - discount_minor - "
                            "refund_minor; cancelled = 0; tax_minor excluded",
        "deduplication": {
            "key": ["dataset", "version", "sale_id"],
            "attribution": "identical overlaps attributed to lexicographically first partition ID",
            "conflicts": "reject",
            "same_partition_duplicates": "reject",
        },
    }
