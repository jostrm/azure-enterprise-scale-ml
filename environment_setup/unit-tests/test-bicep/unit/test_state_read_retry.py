"""Offline: a provider state read is sent again after a cut-short body or a transport failure; a write never is.

aif-138 (2026-11-01): one 20 MB state.json read in the middle of a scale-set deletion arrived cut short; the worker
stopped with single-writer-provider-response-invalid after it had deleted the common group, and kept its claim.
"""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

import pytest


ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("factory_lifecycle_state_read_retry", ROOT / "bootstrap/lib/factory_lifecycle.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)
ENDPOINT = "repos/reviewed/private/git/blobs/0b28dc89"
TRUNCATED = b'{"sha":"0b28dc89","content":"c3Nz'
WHOLE = b'{"sha":"0b28dc89","content":"c3Nz","encoding":"base64"}'


class Answer(io.BytesIO):
    code = 200
    headers = {}

    def read(self, size=-1):
        return super().read(size)


class Opener:
    def __init__(self, *answers):
        self.answers, self.sent = list(answers), []

    def open(self, request, timeout):
        self.sent.append(request.get_method())
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Answer(answer)


def cloud(opener):
    value = fl.Cloud({"identity": {"object_id": "reviewed-identity"},
                      "target": {"tenant_id": "reviewed-tenant", "subscription_id": "reviewed-subscription"},
                      "locks": {"coordination_mode": "single-writer"}}, command_runner=Mock(), opener=opener)
    value.command = Mock(return_value="synthetic-github-token")
    return value


@pytest.fixture
def slept(monkeypatch):
    delays = []
    monkeypatch.setattr(fl.time, "sleep", delays.append)
    return delays


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]


def test_a_cut_short_state_read_is_read_again(slept, capsys):
    opener = Opener(TRUNCATED, WHOLE)
    status, _, parsed = cloud(opener).state_request("gha", "GET", ENDPOINT, None, (200,))
    assert status == 200 and parsed["encoding"] == "base64"
    assert opener.sent == ["GET", "GET"] and slept == [fl.READ_TRANSPORT_RETRY_DELAYS[0]]
    [event] = events(capsys)
    assert event["event"] == "single-writer-provider-response-invalid"
    assert event["attempt"] == 1 and event["retrying"] is True


def test_a_failed_state_read_transport_is_read_again(slept):
    opener = Opener(URLError(ConnectionResetError(10054, "reset")), WHOLE)
    assert cloud(opener).state_request("gha", "GET", ENDPOINT, None, (200,))[2]["sha"] == "0b28dc89"
    assert opener.sent == ["GET", "GET"] and len(slept) == 1


def test_a_state_read_that_stays_cut_short_blocks_after_the_read_attempts(slept, capsys):
    opener = Opener(*[TRUNCATED] * fl.READ_TRANSPORT_ATTEMPTS)
    with pytest.raises(fl.Blocked, match="^single-writer-provider-response-invalid$"):
        cloud(opener).state_request("gha", "GET", ENDPOINT, None, (200,))
    assert len(opener.sent) == fl.READ_TRANSPORT_ATTEMPTS
    assert [event["retrying"] for event in events(capsys)] == [True] * (fl.READ_TRANSPORT_ATTEMPTS - 1) + [False]


@pytest.mark.parametrize("answer, code", [(TRUNCATED, "single-writer-provider-response-invalid"),
                                          (URLError(TimeoutError("timed out")), "single-writer-provider-write-or-read-uncertain")])
def test_a_state_write_is_sent_once_whatever_its_answer(slept, answer, code):
    opener = Opener(answer, WHOLE)
    with pytest.raises(fl.Blocked, match="^" + code + "$"):
        cloud(opener).state_request("gha", "PATCH", "repos/reviewed/private/git/refs/heads/x", {"sha": "a"}, (200,))
    assert opener.sent == ["PATCH"] and slept == []
