"""Test tiers of the Terraform port suite, with the tier mechanism of test-bicep (base/tiers.py).

Tier 1 holds the static contracts (formatting, generated files, parity map, workflows); tier 2 runs
Terraform and Bicep to compare names, parameters and conditions. Unless ``--tiers`` or ``AIF_TEST_TIERS``
asks for less, every tier runs. ``test_tiers.py`` fails when a test file is not listed here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "test-bicep"))

from base.tiers import Tier, TierManifest  # noqa: E402


MANIFEST = TierManifest(default="1-2", tiers=(
    Tier(1, "static", "Terraform formatting, generated files, the Bicep-to-Terraform parity map, the GitHub "
         "Actions template and CI wiring, and this suite's own harness.", (
        "test_format_and_generated.py",
        "test_iac_switch.py",
        "test_parity_map.py",
        "test_terraform_workflow.py",
        "test_tiers.py",
    )),
    Tier(2, "parity", "terraform init/validate/console and bicep build: uniqueString, naming, parameters "
         "and deployment conditions of 11/12/13 against the Bicep templates.", (
        "test_validate.py",
        "test_unique_string.py",
        "test_stage_parity.py",
    )),
))
