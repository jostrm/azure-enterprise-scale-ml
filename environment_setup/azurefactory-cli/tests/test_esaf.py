"""ESAF facade: the six scenario methods a junior developer calls with few parameters (Joakim, 2026-10-31)."""

import copy

import pytest

from azurefactory import esaf
from azurefactory.errors import BlockedError

FOLDER = r"C:\factory\azurefactory"
FACTORY = "4c3dd622-10fb-4cd0-9899-43fca758cce3"
SCALE1 = "949c7a2b-936f-4178-b4cc-e1a0f0b29099"
SCALE2 = "39d2afa3-a320-4abc-a694-eb123792a3a9"
PROJECT1 = "fd972238-3b16-43f3-a327-2040f0bf64ab"
PROJECT2 = "2629a442-5546-4836-a278-46f5cf912ea1"
SUB = "f0fe8b33-73bf-41e4-9997-e3920d793c06"
TENANT = "c157e61b-4a1e-488c-9a0c-d9a23e864a65"
OK = {"can_execute": True, "blockers": [], "confirmation_id": "c-1", "preview_hash": "h" * 64,
      "confirmation_phrase": "PHRASE"}


def catalog(scales=("001",), projects=(("001", "001"),)):
    ids = {"001": SCALE1, "002": SCALE2}
    pids = {"001": PROJECT1, "002": PROJECT2}
    return {"revision": "r" * 64, "factories": [{
        "id": FACTORY, "key": "aif-138", "aifactory_version": "125",
        "scale_sets": [{"id": ids[s], "suffix": s, "environment": "dev", "subscription_id": SUB,
                        "tenant_id": TENANT, "orchestrator": "gha"} for s in scales],
        "projects": [{"id": pids[n], "number": n, "placements": [{"scale_set_id": ids[s], "environment": "dev"}]}
                     for n, s in projects]}]}


class Client:
    """Records the SDK calls the facade composes, like the real AzureFactoryClient answers them."""

    def __init__(self, document, refuse=None):
        self.document, self.calls, self.refuse, self.pending = document, [], refuse or {}, None

    def _call(self, name, *args, **kwargs):
        self.calls.append(name)
        if name in self.refuse:
            refused = self.refuse[name]
            if isinstance(refused, Exception):
                raise refused
            return {"can_execute": False, "blockers": [refused]}
        return copy.deepcopy(OK)

    def catalog_list(self, folder):
        self.calls.append("catalog_list")
        return copy.deepcopy(self.document)

    def scaleset_add_prepare(self, folder, factory_id, scale_sets, *, expected_revision=None):
        self.scale_sets = scale_sets
        self.pending = ("scale_sets", {**scale_sets[0], "id": SCALE2})
        return self._call("scaleset_add_prepare")

    def project_add_prepare(self, folder, factory_id, *, number, display_name="", placements=None,
                            environments=None, settings=None, expected_revision=None):
        self.placements = placements
        self.pending = ("projects", {"id": PROJECT2, "number": number, "placements": placements})
        return self._call("project_add_prepare")

    def catalog_settings_prepare(self, folder, factory_id, settings, *, scale_set_id=None, project_id=None,
                                 expected_revision=None):
        self.settings = (settings, scale_set_id, project_id)
        return self._call("catalog_settings_prepare")

    def catalog_prepare(self, body):
        self.body = body
        return self._call("catalog_prepare:" + body["action"])

    def catalog_confirm(self, folder, confirmation_id):
        self.calls.append("catalog_confirm")
        if self.pending:  # the server saves a confirmed configuration change
            key, item = self.pending
            self.document["factories"][0][key].append(item)
            self.pending = None
        return {"contract_version": 1, "job": {"id": "job-1", "status": "queued"}}

    def enroll_scale_set_prepare(self, body):
        return self._call("enroll_scale_set_prepare")

    def enroll_scale_set_confirm(self, *, folder, confirmation_id, preview_hash, confirmation_phrase):
        self.calls.append("enroll_scale_set_confirm:" + confirmation_phrase)
        return {"status": "enrolled"}

    def authorize_deletion_prepare(self, body):
        return self._call("authorize_deletion_prepare")

    def authorize_deletion_confirm(self, *, folder, confirmation_id, preview_hash, confirmation_phrase):
        self.calls.append("authorize_deletion_confirm")
        return {"status": "authorized"}

    def project_delete_prepare(self, folder, factory_id, project_id, *, environments, include_project_subnets,
                               include_keyvault_and_resource_group, expected_revision, scale_set_id=None,
                               version_ref=None):
        self.deletion = (project_id, environments, include_project_subnets, include_keyvault_and_resource_group)
        return self._call("project_delete_prepare")

    def scaleset_delete_prepare(self, folder, factory_id, scale_set_id, *, expected_revision, version_ref=None):
        self.deleted_scale = scale_set_id
        return self._call("scaleset_delete_prepare")

    def delete_aifactory_prepare(self, body):
        self.factory_body = body
        return self._call("delete_aifactory_prepare")

    def delete_aifactory_confirm(self, *, folder, confirmation_id, preview_hash, confirmation_phrase):
        self.calls.append("delete_aifactory_confirm:" + confirmation_phrase)
        return {"job": {"id": "teardown-1", "status": "queued"}}

    def catalog_job(self, folder, job_id):
        self.calls.append("catalog_job")
        return {"id": job_id, "status": "succeeded", "message": "done"}

    def delete_aifactory_status(self, folder, job_id):
        self.calls.append("delete_aifactory_status")
        return {"job": {"id": job_id, "status": "succeeded"}}


def session(document, **kwargs):
    return esaf.connect(folder=FOLDER, client=Client(document, **kwargs))


def test_code_completion_lists_the_six_scenarios():
    assert {"init_factory", "add_scale_set", "upsert_project", "delete_project", "delete_scale_set",
            "delete_factory"} <= set(esaf.__all__)


def test_add_scale_set_registers_enrolls_and_deploys_its_common():
    s = session(catalog())
    job = esaf.add_scale_set("002", cidr="10.141.0.0/16")
    client = s.client
    assert client.calls[:4] == ["catalog_list", "scaleset_add_prepare", "catalog_confirm", "catalog_list"]
    assert "enroll_scale_set_prepare" in client.calls and "enroll_scale_set_confirm:PHRASE" in client.calls
    assert client.calls[-2:] == ["catalog_prepare:deploy", "catalog_confirm"]
    added = client.scale_sets[0]
    # Defaults come from the factory's existing scale set of the same environment.
    assert added == {"environment": "dev", "suffix": "002", "tenant_id": TENANT, "subscription_id": SUB,
                     "orchestrator": "gha", "network": {"vnet_cidr": "10.141.0.0/16", "max_projects": 3}}
    assert client.body["version_ref"] == "125" and client.body["project_id"] is None
    assert job.id == "job-1" and job.kind == "catalog"


def test_add_scale_set_resumes_an_existing_enrolled_scale_set():
    s = session(catalog(scales=("001", "002")),
                refuse={"enroll_scale_set_prepare": "The selected scale set already has a binding target."})
    esaf.add_scale_set("002", cidr="10.141.0.0/16")
    assert "scaleset_add_prepare" not in s.client.calls
    assert not any(call.startswith("enroll_scale_set_confirm") for call in s.client.calls)
    assert s.client.calls[-2:] == ["catalog_prepare:deploy", "catalog_confirm"]


def test_upsert_project_adds_a_new_project_then_deploys_it():
    s = session(catalog(scales=("001", "002")))
    job = esaf.upsert_project("002", scale_set="002", settings={"tag_costcenter": "lab"})
    assert s.client.placements == [{"environment": "dev", "scale_set_id": SCALE2}]
    assert s.client.calls.count("catalog_confirm") == 3  # add, settings, deploy
    assert s.client.body["action"] == "deploy" and s.client.body["scale_set_id"] == SCALE2
    assert job.id == "job-1"


def test_upsert_project_updates_an_existing_project_in_place():
    s = session(catalog())
    esaf.upsert_project("001", settings={"tag_costcenter": "lab"})
    assert "project_add_prepare" not in s.client.calls
    assert s.client.settings == ({"tag_costcenter": "lab"}, SCALE1, PROJECT1)
    assert s.client.body["project_id"] == PROJECT1 and s.client.body["scale_set_id"] == SCALE1


def test_delete_project_allows_deletion_once_and_deletes_the_project_group():
    s = session(catalog(scales=("001", "002"), projects=(("001", "001"), ("002", "002"))),
                refuse={"authorize_deletion_prepare": BlockedError(
                    "Deletion authorization is blocked: Nothing to change: deletion is already allowed")})
    job = esaf.delete_project("002")
    assert "authorize_deletion_confirm" not in s.client.calls  # already allowed is not a failure
    assert s.client.deletion == (PROJECT2, ["dev"], False, True)
    assert job.id == "job-1"


def test_delete_scale_set_and_delete_factory_confirm_with_the_servers_phrase():
    s = session(catalog(scales=("001", "002")))
    esaf.delete_scale_set("002")
    assert s.client.deleted_scale == SCALE2 and s.client.calls[-1] == "catalog_confirm"
    job = esaf.delete_factory()
    assert s.client.factory_body == {"contract_version": 1, "folder": FOLDER, "factory_id": FACTORY,
                                     "expected_revision": "r" * 64}
    assert s.client.calls[-1] == "delete_aifactory_confirm:PHRASE"
    assert job.kind == "factory-deletion" and job.id == "teardown-1"
    assert job.wait(poll=0)["status"] == "succeeded"


def test_a_refused_review_raises_with_the_servers_blockers():
    session(catalog(), refuse={"catalog_prepare:deploy": "Missing resolved parameters: adminPassword"})
    with pytest.raises(BlockedError, match="adminPassword"):
        esaf.upsert_project("001")


def test_wait_follows_a_catalog_job_to_its_end():
    s = session(catalog())
    job = esaf.upsert_project("001")
    assert job.wait(poll=0) == {"id": "job-1", "status": "succeeded", "message": "done"}
    assert esaf.upsert_project("001", wait=True).result["status"] == "succeeded"


class WorkflowClient(Client):
    def __init__(self):
        super().__init__(catalog())
        self.stages = ["prerequisites", "project-deployment", "complete"]

    def creation_workflow_next(self, folder, workflow_id):
        self.calls.append("next:" + self.stages[0])
        return {"stage": self.stages[0], "can_execute": True, "blockers": [], "confirmation_id": "w-1"}

    def creation_workflow_start(self, folder, workflow_id, confirmation_id, **kwargs):
        self.calls.append("start:" + self.stages.pop(0))
        return {"status": "queued"}

    def creation_workflow_status(self, folder, workflow_id):
        return {"status": "succeeded" if not self.stages else "awaiting-review", "stage": "complete"}


def test_init_factory_drives_every_stage_of_the_creation_workflow():
    client = WorkflowClient()
    esaf.connect(folder=FOLDER, client=client)
    job = esaf.init_factory("ee60a809-891a-4c04-96ff-d406c6eb8d7f", wait=True, poll=0)
    assert [call for call in client.calls if call.startswith("start:")] == [
        "start:prerequisites", "start:project-deployment", "start:complete"]
    assert job.result["status"] == "succeeded"
