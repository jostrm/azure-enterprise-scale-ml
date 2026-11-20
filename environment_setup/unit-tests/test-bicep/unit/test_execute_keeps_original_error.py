"""A pre-mutation failure keeps its own error code when the claim cannot be released (aif-163 run 2478)."""

from .test_factory_lifecycle import FakeCloud, fl, manifest, setup_execute, workspace, no_real_services  # noqa: F401


class RetainingLocks:
    """The single-writer claim is retained on every non-success, so release refuses."""

    def __init__(self, cloud, document):
        self.cloud, self.document, self.held, self.stored = cloud, document, {"scope": "lease"}, []
        self.enrollment = cloud.enrollment

    def acquire(self):
        pass

    def claim_run(self):
        pass

    def store_receipt(self, receipt):
        self.stored.append(dict(receipt))

    def release(self):
        raise fl.Blocked("single-writer-claim-retained-reconciliation-required")


def test_pre_mutation_failure_keeps_its_error_code_when_the_claim_is_retained(monkeypatch, workspace):
    source, execution, receipt = setup_execute(monkeypatch, workspace)
    cloud = FakeCloud()
    cloud.active_run = True
    locks = []
    result = fl.execute(manifest(), source, execution, receipt, cloud=cloud,
                        lock_factory=lambda cloud, document: locks.append(RetainingLocks(cloud, document)) or locks[-1])
    assert result["status"] == "blocked" and not result["mutation_started"]
    assert result["error_code"] == "active-or-queued-remote-run"
    assert result["release_error_code"] == "single-writer-claim-retained-reconciliation-required"
    assert result["locks_retained"] == ["scope"]
    assert locks[0].stored[-1]["error_code"] == "active-or-queued-remote-run"
