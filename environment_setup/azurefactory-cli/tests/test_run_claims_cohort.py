"""A local deletion cohort's retained claim is reviewed with no remote run (aif-138, 2026-11-01)."""

from __future__ import annotations

import pytest

from azurefactory import run_claims
from azurefactory.errors import ConfigError
from test_run_claims import FACTORY, FOLDER, RUN, preview


REQUEST = {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY, "run_id": RUN}


def cohort_preview(**claim):
    value = preview()
    value["operation"] = "delete"
    value["active_claim"] = {**value["active_claim"], "kind": "deletion-cohort", "cohort_hash": "4" * 64, **claim}
    value["remote_run"] = None
    return value


def test_a_finished_local_cohort_claim_review_is_accepted_and_described():
    value = cohort_preview()
    run_claims.validate_claim_preview(REQUEST, value)
    shown = run_claims.describe(value)
    assert shown["Local deletion worker"] == "no GitHub Actions or Azure DevOps run; the local worker finished"
    assert "GitHub Actions run" not in shown and "Azure DevOps run" not in shown


@pytest.mark.parametrize("change", ["run-without-remote", "cohort-without-hash", "cohort-with-remote", "other-kind"])
def test_only_a_local_cohort_review_may_omit_the_remote_run(change):
    value = cohort_preview()
    if change == "run-without-remote":
        value["active_claim"]["kind"] = "run"
    elif change == "cohort-without-hash":
        del value["active_claim"]["cohort_hash"]
    elif change == "cohort-with-remote":
        value["remote_run"] = preview()["remote_run"]
    else:
        value["active_claim"]["kind"] = "deployment-cohort"
    with pytest.raises(ConfigError, match="Nothing was released"):
        run_claims.validate_claim_preview(REQUEST, value)
