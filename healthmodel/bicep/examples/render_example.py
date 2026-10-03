"""Regenerate project001-dev.parameters.json from the anonymized test-factory inventory.

    python bicep/examples/render_example.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aifactory_healthmodel import catalog, naming, planner  # noqa: E402

TARGET = Path(__file__).with_name("project001-dev.parameters.json")
INVENTORY = ROOT / "tests" / "fixtures" / "test-env-resources.json"


def render() -> dict:
    scope = naming.explicit(
        tenant_id="11111111-1111-1111-1111-111111111111", subscription_id="00000000-0000-0000-0000-0000000000aa",
        environment="dev", project_number="001", location="swedencentral", location_suffix="sdc",
        project_resource_group="spider-esml-project001-sdc-dev-001-rg",
        common_resource_group="spider-esml-common-sdc-dev-001", resource_group_prefix="spider-",
        resource_group_suffix="-001",
    )
    rows = json.loads(INVENTORY.read_text(encoding="utf-8"))
    plan = planner.build_plan(catalog.load_catalog(), scope, planner.parse_resources(rows), model_scope="project")
    return planner.bicep_parameters(plan, location="swedencentral")


if __name__ == "__main__":
    TARGET.write_text(json.dumps(render(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET}")
