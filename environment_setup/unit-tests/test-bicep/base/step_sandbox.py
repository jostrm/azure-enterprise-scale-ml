"""What a pipeline step finds next to it, for tests that run a step's inline script in a scratch folder.

A step no longer consists of its inline script alone: deployment steps `source` a shared helper from the
accelerator checkout. A real job has that checkout; a scratch folder does not, so a test that runs the script
there has to provide the same files at the same relative paths.
"""
from __future__ import annotations

from pathlib import Path
import shutil

from base.config import REPO_ROOT

BICEP_DIR = REPO_ROOT / "environment_setup/aifactory/bicep"
# The folder name of the accelerator in a consumer repository (the submodule path).
SUBMODULE = "azure-enterprise-scale-ml"
# Files that inline step scripts source, relative to the bicep folder.
SOURCED_HELPERS = ("scripts/modules/aif-retry.sh",)


def provide_step_helpers(directory: Path) -> Path:
    """Copy the sourced helpers into `directory`, where each host looks for them.

    GitHub Actions runs a step in the consumer root and names the helper by the submodule path; Azure DevOps
    runs it in the bicep folder and names it relative to that. Both are provided, so one scratch folder serves
    the two twins of a step.
    """
    for relative in SOURCED_HELPERS:
        for target in (directory / SUBMODULE / "environment_setup/aifactory/bicep" / relative, directory / relative):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BICEP_DIR / relative, target)
    return directory
