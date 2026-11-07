"""Offline: the factory teardown after its own project pipelines deleted every project group (aif-152, 2026-11-07).

Job 4d970c77: the infra-project pipelines deleted the project groups, and with them pink's ownership record. Pink
registers the scale set's groups for every project, so each project saw several gone groups and no record, and the
freeze refused with factory-delete-exact-project-group-required. A gone group named for the project (AI Factory
project groups carry project<NNN>) is that project's own group, already deleted.
"""

import json

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, seal, workspace, no_real_services  # noqa: F401
from .test_factory_deletion_pipeline import factory_prepared
from .test_single_writer_resumed_absent_project import everything_gone
from .test_single_writer_deletion import single_writer


NAMED = GROUP.rsplit("/", 1)[0] + "/aif-152-esml-project017-sdc-dev-001-rg"
OTHER = GROUP.rsplit("/", 1)[0] + "/aif-152-esml-project018-sdc-dev-001-rg"


def renamed(value, old, new):
    text = json.dumps(value)
    for before, after in ((old, new), (old.lower(), new.lower())):
        text = text.replace('"' + before + '"', '"' + after + '"').replace('"' + before + "/", '"' + after + "/")
    return json.loads(text)


def named_project_group(name=NAMED):
    """factory_prepared with the project group named as AI Factory names it (prefix-...-project017-...-rg)."""
    document, cloud, projects = factory_prepared()
    cloud.bodies = renamed(cloud.bodies, GROUP, name)
    cloud.enrollment = renamed(cloud.enrollment, GROUP, name)
    document = renamed(document, GROUP, name)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    projects = renamed(projects, GROUP, name)
    return document, cloud, projects


def gone(cloud, name=NAMED):
    for key in [key for key in cloud.bodies if key == name.lower() or key.startswith(name.lower() + "/")]:
        del cloud.bodies[key]
    return cloud


def test_scale_set_wide_registration_without_record_names_the_gone_group_by_project_number():
    document, cloud, projects = named_project_group()
    everything_gone(cloud)
    gone(cloud)
    single_writer(document, cloud, "gha")
    projects = [{**projects[0], "registered_resource_ids": [NAMED, COMMON]}]
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    assert data["projects"][0]["resource_group_id"] == NAMED.lower()
    groups = {row["id"].lower(): row for row in data["resource_groups"]}
    assert groups[NAMED.lower()]["already_absent"] is True and groups[NAMED.lower()]["project_number"] == "017"
    assert groups[COMMON.lower()]["project_number"] is None
    document["deletion"] = data
    fl.validate_manifest(seal(document))


def test_a_gone_group_named_for_another_project_is_not_claimed():
    document, cloud, projects = named_project_group(OTHER)
    everything_gone(cloud)
    gone(cloud, OTHER)
    single_writer(document, cloud, "gha")
    projects = [{**projects[0], "registered_resource_ids": [OTHER, COMMON]}]
    with pytest.raises(fl.Blocked, match="factory-delete-exact-project-group-required"):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
