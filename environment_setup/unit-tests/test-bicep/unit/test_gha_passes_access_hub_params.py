"""GitHub Actions pass the access-hub intent to the templates that derive bootstrap-managed DNS (aif-153, 2026-11-08).

13-rgLevel.bicep and 01-foundation.bicep derive bootstrapManagedPrivateDns from access_hub_mode and setup_hub_access:
with an own access hub (integrated + setup_hub_access) the bootstrap owns the private DNS zones and their VNet links.
infra-common.yml never passed the two parameters, so aif-153's common run tried to link ~30 zones a second time:
"Private zone 'privatelink.vaultcore.azure.net' is already linked to the virtual network". Every deployment of a
template that declares them must pass both.
"""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
WORKFLOWS = BICEP / "copy_to_local_settings" / "github-actions"
DECLARES = re.compile(r"^param (access_hub_mode|setup_hub_access)\b", re.M)


def hub_templates():
    return {str(path.relative_to(BICEP)).replace("\\", "/") for path in BICEP.rglob("*.bicep")
            if len(set(DECLARES.findall(path.read_text(encoding="utf-8")))) == 2}


def deployments():
    """(workflow, line, template, the deployment command's text) for each az deployment of a hub template."""
    templates = hub_templates()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            match = re.search(r"--template-file \"azure-enterprise-scale-ml/environment_setup/aifactory/bicep/([^\"]+)\"", line)
            if not match or match[1] not in templates:
                continue
            command = []
            for text in lines[number:]:
                command.append(text)
                if not text.rstrip().endswith("\\"):
                    break
            yield path.name, number + 1, match[1], "\n".join(command)


def test_both_hub_templates_are_deployed_by_the_workflows():
    assert {"esml-common/main/13-rgLevel.bicep", "esml-genai-1/01-foundation.bicep"} <= hub_templates()
    assert {template for _, _, template, _ in deployments()} == hub_templates()


@pytest.mark.parametrize("name,number,template,command", list(deployments()), ids=lambda item: str(item)[:60])
def test_a_hub_template_deployment_passes_the_access_hub_intent(name, number, template, command):
    assert 'access_hub_mode="${{ env.access_hub_mode }}"' in command, name + ":" + str(number)
    assert "setup_hub_access=\"${{ env.setup_hub_access || 'false' }}\"" in command, name + ":" + str(number)
