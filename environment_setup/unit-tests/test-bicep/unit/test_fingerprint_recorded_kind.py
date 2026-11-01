"""A listed-only child is fingerprinted as the type it was recorded with, at review and at every re-check."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("factory_lifecycle_recorded_kind", ROOT / "bootstrap/lib/factory_lifecycle.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)

GROUP = "/subscriptions/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/resourceGroups/reviewed"

KIND = "microsoft.operationalinsights/workspaces/tables"
TABLE = GROUP + "/providers/Microsoft.OperationalInsights/workspaces/la/tables/AACAudit"


def test_a_typeless_log_analytics_table_is_fingerprinted_as_its_recorded_type():
    # ARM lists Log Analytics tables without "type": the review hashed them with their volatile fields removed, so the
    # check must too (aif-138 2026-11-01: all 697 tables failed inventory-changed-since-prepare on a quiet workspace).
    body = {"id": TABLE, "name": "AACAudit", "properties": {"retentionInDays": 30, "schema": {"columns": [1]}}}
    item = {"id": TABLE.lower(), "type": KIND, "etag": fl.resource_etag(body, {}, KIND),
            "body_hash": fl.resource_digest(body, KIND)}
    fl.verify_fingerprint(item, body, {})
    body["properties"]["schema"] = {"columns": [1, 2]}  # Microsoft moves a table's schema centrally
    fl.verify_fingerprint(item, body, {})
    body["properties"]["retentionInDays"] = 90
    with pytest.raises(fl.Blocked, match="inventory-changed-since-prepare"):
        fl.verify_fingerprint(item, body, {})
