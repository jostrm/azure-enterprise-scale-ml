"""Revision contract for the agent Container App: one active revision, so redeploys never leave idle replicas behind."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_the_application_keeps_a_single_active_revision():
    bicep = (ROOT / "infra" / "application.bicep").read_text("utf-8")
    # Multiple mode with minReplicas >= 1 kept every earlier revision running (and billed) after each deploy.
    assert re.findall(r"activeRevisionsMode: '(\w+)'", bicep) == ["Single"]


def test_the_latest_revision_still_receives_all_traffic():
    bicep = (ROOT / "infra" / "application.bicep").read_text("utf-8")
    assert re.search(r"traffic: \[\{\s*latestRevision: true\s*weight: 100\s*\}\]", bicep)


def test_the_rollback_guidance_reactivates_the_known_good_revision():
    readme = (ROOT / "readme.md").read_text("utf-8")
    assert "shift traffic to the known-good revision" not in readme
    assert "az containerapp revision activate" in readme
