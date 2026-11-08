"""Step env never replaces an AI Factory setting with a repository variable alone (aif-153, 2026-11-08).

aif-153 (private factory, own hub, API-2-Pipelines): the API passed enableCosmosDB=true in the run's JSON
configuration and the job env had it, but the "Preflight quota & policy checks" step set
``enableCosmosDB: ${{ vars.ENABLE_COSMOS_DB || 'false' }}``. Preflight read false and failed every run with
"the private Foundry capability-host bundle cannot be deselected". A step's camelCase setting must prefer the job's
value (``env.<key>``), as enableDatabricks already did; the repository variable and the default stay fallbacks.
"""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings" / "github-actions"
# A step-level env entry (10 spaces) whose camelCase key reads a repository variable.
STEP_SETTING = re.compile(r"^ {10}(?P<key>[a-z][A-Za-z0-9_]*): \$\{\{ (?P<value>.*vars\..*) \}\}\s*$")


def step_settings():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = STEP_SETTING.match(line)
            if match:
                yield path.name, number, match["key"], match["value"]


def test_the_workflows_have_step_settings_to_check():
    assert any(key == "enableCosmosDB" for _, _, key, _ in step_settings())


@pytest.mark.parametrize("name,number,key,value", list(step_settings()),
                         ids=lambda item: str(item) if not isinstance(item, str) or "${" not in item else "")
def test_a_step_setting_prefers_the_job_value(name, number, key, value):
    assert value.startswith("env." + key + " || "), (
        name + ":" + str(number) + " sets " + key + " from a repository variable only; use env." + key + " first")
