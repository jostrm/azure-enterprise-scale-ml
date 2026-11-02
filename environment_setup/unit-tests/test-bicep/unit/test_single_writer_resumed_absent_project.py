"""Offline: a single-writer factory deletion resumed after its project group is gone releases its claim.

aif-138 (2026-11-02, run21): the resumed factory deletion deleted the whole common group (113 rows), then the claim
release refused with single-writer-deletion-receipt-incomplete: it required deleted_resources to name every reviewed
row, but the already-absent project group is only observed (its project stage is no longer dispatched). Rows the review
recorded as already absent are proven by the release's own 404 check instead.
"""

from .test_factory_lifecycle import fl, GROUP, seal, workspace, no_real_services  # noqa: F401
from .test_factory_deletion_pipeline import factory_prepared
from .test_factory_deletion_resumed_project import project_stage_done
from .test_single_writer_deletion import single_writer, run


def test_a_resumed_single_writer_factory_deletion_releases_with_the_absent_group_observed(workspace, monkeypatch):
    document, cloud, projects = factory_prepared()
    project_stage_done(cloud)
    provider = single_writer(document, cloud, "gha")
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    document = seal(document)
    dispatched = []
    monkeypatch.setattr(fl, "github_scoped", lambda *args: dispatched.append(args))
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "succeeded", result
    assert not dispatched and provider.state()["active"] is None
    receipt = provider.state()["records"]["runs/" + document["run_id"] + ".json"]
    assert GROUP.lower() not in {value.lower() for value in receipt["deleted_resources"]}
    assert GROUP.lower() in {value.lower() for value in receipt["observed_absent"]}


def everything_gone(cloud):
    """What run21 left: the project group and the whole common group are gone."""
    from .test_factory_lifecycle import COMMON
    project_stage_done(cloud)
    for key in [key for key in cloud.bodies if key == COMMON.lower() or key.startswith(COMMON.lower() + "/")]:
        del cloud.bodies[key]
    return cloud


def test_a_factory_whose_groups_are_all_gone_is_reviewed_and_released_without_any_delete(workspace, monkeypatch):
    # aif-138 2026-11-02 after run21: only the catalog entry and the retained claim were left.
    document, cloud, projects = factory_prepared()
    everything_gone(cloud)
    provider = single_writer(document, cloud, "gha")
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    document = seal(document)
    fl.validate_manifest(document)
    groups = document["deletion"]["resource_groups"]
    assert groups and all(row.get("already_absent") is True for row in groups if row["delete"])
    assert not [row for row in document["deletion"]["resources"] if row["delete"]]
    monkeypatch.setattr(fl, "github_scoped", lambda *args: (_ for _ in ()).throw(AssertionError("dispatched")))
    deleted_before = list(cloud.deleted)
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "succeeded", result
    assert cloud.deleted == deleted_before and provider.state()["active"] is None
    child, = result["children"]
    assert child["deleted_resources"] == []
