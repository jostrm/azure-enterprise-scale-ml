"""Offline: Storage answers a deleted child with 400 ResourceNotFound; a read that accepts absence takes it as 404.

aif-138 (2026-11-02): the factory deletion's common stage deleted a storage account's private endpoint connection;
its wait-for-absence GET got 400 {"error": {"code": "ResourceNotFound"}} instead of 404 and the run stopped with
remote-request-failed-400. The refusal event also logged error_code null, because an earlier helper had already
read the error body.
"""

import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from .test_state_read_retry import cloud as make_cloud, events, slept, fl  # noqa: F401

CONNECTION = ("https://management.azure.com/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/rg"
              "/providers/Microsoft.Storage/storageAccounts/st/privateEndpointConnections/st.14de?api-version=2026-09-01")


class Refusing:
    def __init__(self, code, error_code):
        self.code, self.body, self.sent = code, json.dumps({"error": {"code": error_code, "message": "x"}}).encode(), []

    def open(self, request, timeout):
        self.sent.append(request.get_method())
        raise HTTPError(request.full_url, self.code, "refused", {}, io.BytesIO(self.body))


def cloud(opener):
    value = make_cloud(opener)
    value.token = Mock(return_value="synthetic-arm-token")
    return value


def test_a_400_resource_not_found_is_absent_for_a_read_that_accepts_404():
    status, _, body = cloud(Refusing(400, "ResourceNotFound")).request("GET", CONNECTION, fl.ARM, allowed=(200, 404))
    assert status == 404 and body["error"]["code"] == "ResourceNotFound"


@pytest.mark.parametrize("allowed, error_code", [((200,), "ResourceNotFound"), ((200, 404), "InvalidResourceName")])
def test_any_other_400_still_fails_and_names_its_error_code(capsys, allowed, error_code):
    with pytest.raises(fl.Blocked, match="^remote-request-failed-400$"):
        cloud(Refusing(400, error_code)).request("GET", CONNECTION, fl.ARM, allowed=allowed)
    [event] = events(capsys)
    assert (event["event"], event["status"], event["error_code"]) == ("remote-request-refused", 400, error_code)


def test_a_write_answered_400_resource_not_found_still_fails():
    with pytest.raises(fl.Blocked, match="^remote-request-failed-400$"):
        cloud(Refusing(400, "ResourceNotFound")).request("DELETE", CONNECTION, fl.ARM, allowed=(200, 202, 204, 404))
