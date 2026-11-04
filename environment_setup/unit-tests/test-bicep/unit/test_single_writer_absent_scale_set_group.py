"""Offline: a single-writer scale-set deletion whose group an earlier run already removed releases its claim.

aif-145 Scenario 5 run32 (2026-11-04, provider run 6f452bfc): run 0d29bd55 deleted the common group, then failed on a
GitHub 403. The re-review froze the group already absent, but delete_owned_groups still wrote it into deleted_resources
while the cohort release counts an already-absent row as observed, never deleted (766d7382). Every attempt ended
single-writer-deletion-receipt-incomplete with the claim kept. The group is now reported in observed_absent, as pink's
receipt check and the factory deletion already expect.
"""

from .test_factory_lifecycle import fl, CohortCloud, GROUP, manifest, seal, workspace, no_real_services  # noqa: F401
from .test_single_writer_deletion import single_writer, run

ABSENT = GROUP + "-gone"


class AbsentGroupCloud(CohortCloud):
    def __init__(self):
        super().__init__()
        self.group_deletes = []

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if resource_id.lower() == ABSENT.lower():
            assert method == "GET" and 404 in allowed, (method, resource_id)
            return 404, {}, {"error": {"code": "ResourceGroupNotFound", "message": "Resource group could not be found."}}
        if method == "DELETE" and fl.RG_ID.fullmatch(resource_id):
            self.group_deletes.append(resource_id)
        return super().arm(method, resource_id, api_version, allowed, headers)


def absent_scale_set(kind):
    cloud, document = AbsentGroupCloud(), manifest()
    document["locks"]["scopes"] = [GROUP, ABSENT]
    cloud.enrollment["scopes"][ABSENT.lower()] = dict(cloud.enrollment["scopes"][GROUP.lower()])
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    provider = single_writer(document, cloud, kind)
    document["deletion"] = fl.freeze_deletion_inventory(cloud, document, {})
    return seal(document), cloud, provider


def test_the_already_absent_group_is_observed_and_the_single_writer_claim_released(workspace, monkeypatch):
    document, cloud, provider = absent_scale_set("gha")
    groups = {row["id"]: row for row in document["deletion"]["resource_groups"]}
    assert groups[ABSENT]["already_absent"] is True
    result = run(workspace, monkeypatch, [document], cloud)
    assert result["status"] == "succeeded", result.get("error_code")
    assert provider.state()["active"] is None and cloud.group_deletes == [GROUP]
    receipt = provider.state()["records"]["runs/" + document["run_id"] + ".json"]
    assert receipt["observed_absent"] == [ABSENT]
    assert ABSENT.lower() not in {value.lower() for value in receipt["deleted_resources"]}
    assert GROUP.lower() in {value.lower() for value in receipt["deleted_resources"]}
