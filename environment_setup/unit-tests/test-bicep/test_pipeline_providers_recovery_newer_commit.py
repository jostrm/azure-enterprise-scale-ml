"""Recovery may run from a newer consumer commit that descends from the stuck run's commit (aif-163 run 2480)."""
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap/lib"))
import pipeline_dispatch as dispatch
import pipeline_provider as provider
from test_pipeline_providers_continuations import PARENT, HASH, context, record, PredecessorTraffic

NEWER = "a" * 40


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live recovery call forbidden"))


class AncestryTraffic(PredecessorTraffic):
    """Answers the provider's commit comparison; every other GET is the stuck run."""

    def __init__(self, parent, base_of=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.base_of = base_of or parent["plan"]["provider_context"]["consumer_commit"]

    def request(self, method, url, body=None, raw=False):
        old = self.parent["plan"]["provider_context"]["consumer_commit"]
        if "/compare/" in url:
            assert method == "GET" and url.endswith(f"/compare/{old}...{NEWER}")
            self.calls.append(url)
            ahead = self.base_of == old
            return 200, {}, {"status": "ahead" if ahead else "diverged", "behind_by": 0 if ahead else 2,
                             "ahead_by": 3, "merge_base_commit": {"sha": self.base_of}}
        if "/diffs/commits?" in url:
            assert method == "GET" and f"baseVersion={old}" in url and f"targetVersion={NEWER}" in url
            assert "/git/repositories/factory/" in url
            self.calls.append(url)
            return 200, {}, {"commonCommit": self.base_of, "aheadCount": 3,
                             "behindCount": 0 if self.base_of == old else 2}
        return super().request(method, url, body, raw)


def stuck(provider_name):
    prior = record(provider_name)
    prior.update(status="reconciliation-required", admission={"status": "held"})
    prior.pop("finalization")
    reader = Mock()
    reader._load.return_value = ("rev", prior)
    return prior, reader


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_recovery_accepts_a_newer_consumer_commit_that_descends_from_the_stuck_run(provider_name):
    prior, reader = stuck(provider_name)
    transport = AncestryTraffic(prior, mutation="failed")
    ctx = dict(context(provider_name, 8), correlation_id="f" * 32, consumer_commit=NEWER)
    provider.wait_for_predecessor(PARENT, HASH, ctx, recovery=True, reader=reader, transport=transport)
    assert any("/compare/" in url or "/diffs/commits?" in url for url in transport.calls)
    reader.observe.assert_not_called()


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_recovery_refuses_a_consumer_commit_that_does_not_descend_from_the_stuck_run(provider_name):
    prior, reader = stuck(provider_name)
    ctx = dict(context(provider_name, 8), correlation_id="f" * 32, consumer_commit=NEWER)
    with pytest.raises(dispatch.DispatchError, match="recovery-consumer-commit-not-descendant"):
        provider.wait_for_predecessor(PARENT, HASH, ctx, recovery=True, reader=reader,
                                      transport=AncestryTraffic(prior, base_of="9" * 40, mutation="failed"))


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_continuation_still_requires_the_exact_consumer_commit(provider_name):
    parent = record(provider_name)
    reader = Mock()
    reader._load.return_value = ("rev", parent)
    ctx = dict(context(provider_name, 8), correlation_id="f" * 32, consumer_commit=NEWER)
    with pytest.raises(dispatch.DispatchError, match="continuation-predecessor-binding-mismatch"):
        provider.wait_for_predecessor(PARENT, HASH, ctx, reader=reader, transport=AncestryTraffic(parent),
                                      max_polls=1, sleep=lambda _: None)


@pytest.mark.parametrize("provider_name", ["gha", "ado"])
def test_recovery_from_a_newer_commit_keeps_every_other_binding(provider_name):
    prior, reader = stuck(provider_name)
    ctx = dict(context(provider_name, 8), correlation_id="f" * 32, consumer_commit=NEWER, source_commit="9" * 40)
    with pytest.raises(dispatch.DispatchError, match="continuation-predecessor-binding-mismatch"):
        provider.wait_for_predecessor(PARENT, HASH, ctx, recovery=True, reader=reader,
                                      transport=AncestryTraffic(prior, mutation="failed"))
