"""Offline: a Log Analytics workspace's tables leave with the workspace, and the frozen manifest keeps only their
fingerprint body.

aif-144 (2026-11-04, delete_factory run5/run6): one frozen manifest was 9.30 MB against the protected worker's 8 MB, and
697 of its 1298 resources were the common workspace's tables with their full schema bodies. The schema is already
outside the fingerprint (VOLATILE_FIELDS), so the manifest holds the fingerprint body and the row's body_hash is
unchanged. Each table was also sent a DELETE of its own; deleting the workspace removes them.
"""

from .test_factory_lifecycle import fl, GROUP, OWNER, seal, no_real_services  # noqa: F401
from .test_selective_project_deletion import tagged
from .test_factory_deletion_pipeline import factory_prepared

WORKSPACE = GROUP + "/providers/Microsoft.OperationalInsights/workspaces/la-project"
TABLE = WORKSPACE + "/tables/AppTraces"
TABLE_KIND = "Microsoft.OperationalInsights/workspaces/tables"
SCHEMA = {"name": "AppTraces", "columns": [{"name": "column%03d" % index, "type": "string"} for index in range(200)]}


def with_workspace():
    document, cloud, projects = factory_prepared()
    cloud.bodies[WORKSPACE.lower()] = tagged(WORKSPACE, "Microsoft.OperationalInsights/workspaces", OWNER)
    cloud.bodies[TABLE.lower()] = tagged(TABLE, TABLE_KIND, OWNER, {"retentionInDays": 30, "schema": SCHEMA})
    old_schema, old_operations, old_collection = cloud.provider_schema, cloud.provider_operations, cloud.collection

    def schema(namespace):
        if namespace.lower() == "microsoft.operationalinsights":
            return {"resourceTypes": [{"resourceType": name, "apiVersions": ["2025-02-01"]}
                                      for name in ("workspaces", "workspaces/tables")]}
        return old_schema(namespace)

    def operations(namespace):
        if namespace.lower() == "microsoft.operationalinsights":
            return ["microsoft.operationalinsights/" + kind + "/" + action
                    for kind in ("workspaces", "workspaces/tables") for action in ("read", "write", "delete")]
        return old_operations(namespace)

    def collection(path, api_version, extension=False):
        if path.lower().endswith("/tables"):
            return [dict(body) for key, body in sorted(cloud.bodies.items()) if key.startswith(path.lower() + "/")], None
        return old_collection(path, api_version, extension)

    cloud.provider_schema, cloud.provider_operations, cloud.collection = schema, operations, collection
    unsealed = dict(document)
    unsealed["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    return seal(unsealed), cloud


def table_row(document):
    return next(row for row in document["deletion"]["resources"] if row["id"].lower() == TABLE.lower())


def test_a_table_is_deleted_with_its_workspace():
    document, _ = with_workspace()
    fl.validate_manifest(document)
    row = table_row(document)
    assert row["independent_delete"] is False
    assert row["delete_via_parent"] == WORKSPACE.lower()


def test_the_manifest_freezes_a_table_without_its_schema_and_with_the_same_body_hash():
    document, cloud = with_workspace()
    frozen = document["deletion"]["bodies"][TABLE.lower()]
    assert "schema" not in frozen["properties"]
    assert frozen["properties"]["retentionInDays"] == 30
    assert table_row(document)["body_hash"] == fl.resource_digest(cloud.bodies[TABLE.lower()], TABLE_KIND.lower())
