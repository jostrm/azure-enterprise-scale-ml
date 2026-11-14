"""Offline contract: no command in a workflow or pipeline template is cut short by a space after a backslash.

In bash a backslash only continues the line when it is the last character. A backslash followed by a space ends
the command there, without the parameters below it, and the next line runs as a command of its own
("--parameters: command not found"). The stage job of github-actions/infra-common.yml lost five parameters of
its networking deployment that way (common_bastion_subnet_cidr, env, network_env, cidr_range, IPwhiteList);
the dev and prod jobs did not have the space.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[4]
SETTINGS = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"


def template_files() -> list[Path]:
    files = sorted((SETTINGS / "github-actions").glob("*.yml")) + sorted(
        (SETTINGS / "azure-devops/esml-yaml-pipelines").rglob("*.yaml")) + sorted((ROOT / "bootstrap/templates").glob("*.yml"))
    assert len(files) >= 35
    return files


@pytest.mark.parametrize("path", template_files(), ids=lambda p: p.name)
def test_no_line_continuation_is_broken_by_a_trailing_space(path):
    broken = [f"{path.name}:{number}: {line.strip()[:90]}"
              for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
              if re.search(r"\\[ \t]+$", line) and not line.lstrip().startswith("#")]
    assert not broken, "a space after the line-continuation backslash:\n" + "\n".join(broken)


def test_the_three_environment_jobs_pass_the_same_networking_parameters():
    """dev, stage and prod run the same networking deployment; none may pass fewer parameters than the others."""
    import yaml
    document = yaml.safe_load((SETTINGS / "github-actions/infra-common.yml").read_text(encoding="utf-8"))
    names = {}
    for job_name, job in document["jobs"].items():
        for step in job.get("steps", []):
            if step.get("name") == "02_az_bicep_private_networking":
                lines = step["run"].splitlines()
                start = next(index for index, line in enumerate(lines) if "az deployment sub create" in line)
                command = []
                for line in lines[start:]:
                    command.append(line)
                    if not line.endswith("\\"):
                        break
                names[job_name] = sorted(re.findall(r"--parameters (\w+)=", "\n".join(command)))
    assert len(names) == 3, names.keys()
    reference = names["common-dev"]
    assert len(reference) >= 30
    for job_name, parameters in names.items():
        assert parameters == reference, f"{job_name} passes other networking parameters than common-dev"
