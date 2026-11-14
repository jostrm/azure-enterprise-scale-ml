"""Container Apps jobs and apps leave before their managed environment.

Live evidence (2026-11-14, aif-160, GitHub Actions infra-project run 43532570166, step
18_Delete_Service_If_Not_Enabled_And_Exists): ARM refused the environment DELETE with
ManagedEnvironmentHasContainerAppsJobs because the AI Factory Agent knowledge refresh job
(aifactory-agent-refresh-dev) was still bound to aca-env-prj001-sdc-dev-wbjs3-001, so every project with
Agent Chat enabled could not be deleted.
"""

from unit.test_project_deletion_lifecycle import (
    GROUP, body, deletion, error, invoke,
    forbid_real_commands,  # noqa: F401  (autouse fixture: no real Azure CLI calls)
)


ENV_TYPE = "Microsoft.App/managedEnvironments"
ENV_ID = f"{GROUP}/providers/{ENV_TYPE}/aca-env-prj002-sdc-dev-salt-001"
OTHER_ENV_ID = f"{GROUP}/providers/{ENV_TYPE}/aca-env-other"
JOBS = f"{GROUP}/providers/Microsoft.App/jobs"
APPS = f"{GROUP}/providers/Microsoft.App/containerApps"
JOB_ID = JOBS + "/aifactory-agent-refresh-dev"
APP_ID = APPS + "/aifactory-agent-project002-dev"
FOREIGN_APP_ID = APPS + "/bound-elsewhere"
CHILDREN = ["aca-environment-children", "--name", "aca-env-prj002-sdc-dev-salt-001"]


def job(resource_id=JOB_ID, environment=ENV_ID, state="Succeeded"):
    item = body(resource_id, state)
    item["properties"]["environmentId"] = environment
    return item


def app(resource_id=APP_ID, environment=ENV_ID, state="Succeeded"):
    item = body(resource_id, state)
    item["properties"]["managedEnvironmentId"] = environment
    item["properties"]["environmentId"] = environment
    return item


def page(*items):
    return {"value": list(items)}


def test_bound_job_and_app_are_confirmed_gone_before_the_environment_may_go():
    status, runner, _ = invoke([
        ("GET", ENV_ID, body(ENV_ID)),
        ("GET", JOBS, page(job())),
        ("GET", APPS, page(app(), app(FOREIGN_APP_ID, OTHER_ENV_ID))),
        ("GET", JOB_ID, job()), ("DELETE", JOB_ID, None),
        ("GET", JOB_ID, job(state="Deleting")), ("GET", JOB_ID, error()),
        ("GET", APP_ID, app()), ("DELETE", APP_ID, None), ("GET", APP_ID, error()),
        ("GET", JOBS, page()),
        ("GET", APPS, page(app(FOREIGN_APP_ID, OTHER_ENV_ID))),
    ], CHILDREN, timeout=30)
    assert status == 0
    # Jobs first (the live blocker), then apps; an app bound to another environment is never touched.
    assert [call[1] for call in runner.calls if call[0] == "DELETE"] == [JOB_ID, APP_ID]


def test_a_bound_job_still_listed_after_its_delete_fails_the_step():
    status, _, _ = invoke([
        ("GET", ENV_ID, body(ENV_ID)),
        ("GET", JOBS, page(job())),
        ("GET", APPS, page()),
        ("GET", JOB_ID, job()), ("DELETE", JOB_ID, None), ("GET", JOB_ID, error()),
        ("GET", JOBS, page(job())),
        ("GET", APPS, page()),
    ], CHILDREN, timeout=30)
    assert status != 0


def test_absent_or_deleting_environment_needs_no_child_calls():
    status, runner, _ = invoke([("GET", ENV_ID, error())], CHILDREN)
    assert status == 0 and len(runner.calls) == 1
    status, runner, _ = invoke([("GET", ENV_ID, body(ENV_ID, "Deleting"))], CHILDREN)
    assert status == 0 and len(runner.calls) == 1


def test_container_apps_types_are_supported_by_the_confirming_helper():
    status, _, _ = invoke([
        ("GET", ENV_ID, body(ENV_ID)), ("DELETE", ENV_ID, None), ("GET", ENV_ID, error()),
    ], ["resource", "--resource-type", ENV_TYPE, "--name", "aca-env-prj002-sdc-dev-salt-001"])
    assert status == 0
    args = deletion.arguments(["--subscription", "s", "--resource-group", "g", *CHILDREN])
    assert args.action == "aca-environment-children" and args.name == "aca-env-prj002-sdc-dev-salt-001"


def test_factory_deletion_orders_bound_jobs_and_apps_before_their_environment():
    from unit.test_factory_lifecycle import fl

    environment = body(ENV_ID)
    rows = [
        {"id": item["id"], "type": item["type"], "delete": True,
         "depends_on": fl.project_resource_dependencies(item)}
        for item in (environment, job(), app())
    ]
    order = [row["id"] for row in fl.factory_deletion_module().ordered_resources(rows)]
    assert order.index(JOB_ID) < order.index(ENV_ID) and order.index(APP_ID) < order.index(ENV_ID)
