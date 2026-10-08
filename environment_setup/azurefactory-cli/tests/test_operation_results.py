import pytest

from azurefactory import FailureError
from azurefactory.operation_results import legacy_execution_result


@pytest.mark.parametrize("status,terminal", [
    ("draft", False), ("queued", False), ("running", False),
    ("submitted", True), ("failed", True), ("interrupted", True),
])
def test_legacy_result_never_confuses_script_completion_with_deployment(status, terminal):
    response = {"status": status, "job_id": "local-job"}
    result = legacy_execution_result(response)
    assert result == {
        "contract_version": 1,
        "completion_scope": "local-script",
        "local_terminal": terminal,
        "deployment_verified": False,
    }
    assert response == {"status": status, "job_id": "local-job"}


def test_server_execution_result_is_validated_without_losing_extensions():
    result = legacy_execution_result({"status": "submitted"})
    result["future_detail"] = "additional evidence"
    assert legacy_execution_result({"status": "submitted", "execution_result": result}) == result


@pytest.mark.parametrize("status", [None, "", "mystery", "succeeded", "SUBMITTED", [], {}])
def test_unknown_or_incompatible_legacy_status_fails_closed(status):
    with pytest.raises(FailureError, match="legacy execution"):
        legacy_execution_result({"status": status})


@pytest.mark.parametrize("change", [
    {"contract_version": True}, {"contract_version": 2},
    {"completion_scope": "deployment"}, {"local_terminal": False},
    {"local_terminal": 1}, {"deployment_verified": True}, {"deployment_verified": 0},
])
def test_contradictory_execution_acknowledgements_are_not_reinterpreted(change):
    result = legacy_execution_result({"status": "submitted"})
    result.update(change)
    with pytest.raises(FailureError, match="legacy execution"):
        legacy_execution_result({"status": "submitted", "execution_result": result})


@pytest.mark.parametrize("result", [None, {}, [], "submitted"])
def test_present_but_malformed_metadata_is_not_treated_as_an_older_api(result):
    with pytest.raises(FailureError, match="legacy execution"):
        legacy_execution_result({"status": "submitted", "execution_result": result})
