"""Foundry V2 children are confirmed gone before the account delete; timed-out deletes re-read state.

Live evidence (2026-11-07, aif-151/152 in byor runs 42405428104, 42399439947, 42411231617): nested project
DELETEs answer 202, the account delete 1-3 s later failed with CannotDeleteResource, and an account delete
CLI timeout stopped the pipeline although ARM DELETE is idempotent.
"""

import subprocess
from pathlib import Path

from unit.test_project_deletion_lifecycle import (
    FOUNDRY_ID, ROOT, body, deletion, error, invoke, raw_error, DBX_ID, RESOURCE,
    forbid_real_commands,  # noqa: F401  (autouse fixture: no real Azure CLI calls)
)


PROJECTS = FOUNDRY_ID + "/projects"
PROJECT = PROJECTS + "/proj1"
PROJECT_HOSTS = PROJECT + "/capabilityHosts"
PROJECT_HOST = PROJECT_HOSTS + "/caphostproj"
ACCOUNT_HOSTS = FOUNDRY_ID + "/capabilityHosts"
ACCOUNT_HOST = ACCOUNT_HOSTS + "/caphostacct"
CHILDREN = ["foundry-children", "--name", "foundry"]
SHELL = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "delete-services-if-disabled.sh"


def child(resource_id, state="Succeeded"):
    item = body(resource_id, state)
    item["name"] = "/".join(resource_id.split("/providers/")[-1].split("/")[2::2])
    return item


def page(*items):
    return {"value": list(items)}


def test_nested_project_delete_is_polled_until_absent_before_returning():
    status, runner, clock = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page(child(PROJECT))),
        ("GET", PROJECT_HOSTS, page(child(PROJECT_HOST))),
        ("GET", PROJECT_HOST, child(PROJECT_HOST)), ("DELETE", PROJECT_HOST, None),
        ("GET", PROJECT_HOST, child(PROJECT_HOST, "Deleting")), ("GET", PROJECT_HOST, error()),
        ("GET", ACCOUNT_HOSTS, page(child(ACCOUNT_HOST))),
        ("GET", ACCOUNT_HOST, child(ACCOUNT_HOST)), ("DELETE", ACCOUNT_HOST, None),
        ("GET", ACCOUNT_HOST, error()),
        ("GET", PROJECT, child(PROJECT)), ("DELETE", PROJECT, None),
        # 202 Accepted: the project is still there for a few seconds.
        ("GET", PROJECT, child(PROJECT, "Deleting")), ("GET", PROJECT, child(PROJECT, "Deleting")),
        ("GET", PROJECT, error()),
        ("GET", PROJECTS, page()),
    ], CHILDREN, timeout=30)
    assert status == 0
    deletes = [call[1] for call in runner.calls if call[0] == "DELETE"]
    assert deletes == [PROJECT_HOST, ACCOUNT_HOST, PROJECT]
    # Each confirmation poll waits ~1 s, never the 2 s service poll interval.
    assert clock.now == 3


def test_project_still_listed_after_confirmation_blocks_account_delete():
    status, runner, _ = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page()),
        ("GET", ACCOUNT_HOSTS, page()),
        ("GET", PROJECTS, page(child(PROJECT))),
    ], CHILDREN)
    assert status != 0
    assert not any(call[0] == "DELETE" for call in runner.calls)


def test_account_caphost_bad_request_warns_and_projects_still_go(capsys):
    status, runner, _ = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page(child(PROJECT))),
        ("GET", PROJECT_HOSTS, page()),
        ("GET", ACCOUNT_HOSTS, page(child(ACCOUNT_HOST))),
        ("GET", ACCOUNT_HOST, child(ACCOUNT_HOST)),
        ("DELETE", ACCOUNT_HOST, error("BadRequest", "Capability host cannot be deleted.")),
        ("GET", PROJECT, child(PROJECT)), ("DELETE", PROJECT, None), ("GET", PROJECT, error()),
        ("GET", PROJECTS, page()),
    ], CHILDREN)
    assert status == 0
    assert "account capability host was not deleted (BadRequest)" in capsys.readouterr().err
    assert [call[1] for call in runner.calls if call[0] == "DELETE"] == [ACCOUNT_HOST, PROJECT]


def test_absent_or_deleting_account_needs_no_child_calls():
    status, runner, _ = invoke([("GET", FOUNDRY_ID, error())], CHILDREN)
    assert status == 0 and len(runner.calls) == 1
    status, runner, _ = invoke([("GET", FOUNDRY_ID, body(FOUNDRY_ID, "Deleting"))], CHILDREN)
    assert status == 0 and len(runner.calls) == 1


def timeout(kwargs):
    raise subprocess.TimeoutExpired("az", kwargs["timeout"])


def test_delete_timeout_rereads_state_and_waits_for_deleting_resource():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, timeout),
        ("GET", DBX_ID, body(state="Deleting")), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1


def test_delete_timeout_with_unchanged_state_resubmits_idempotent_delete():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, timeout),
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, None), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 2


def test_delete_timeout_then_resource_gone_is_success():
    status, _, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, timeout), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0


def test_read_timeout_is_retried_before_absence_is_decided():
    status, runner, _ = invoke([
        ("GET", DBX_ID, timeout), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0 and len(runner.calls) == 2


def test_shell_deletes_foundry_children_through_the_confirming_helper_before_the_account():
    text = SHELL.read_text(encoding="utf-8")
    block = text.split("# AI FOUNDRY V2 ACCOUNT", 1)[1].split("# AI SERVICES ACCOUNT", 1)[0]
    children = block.index('aif_delete foundry-children --name "$aif2_name"')
    endpoints = block.index('delete_private_endpoints "$aif2_name"')
    account = block.rindex('aif_delete resource --resource-type "Microsoft.CognitiveServices/accounts" --name "$aif2_name"')
    assert children < endpoints < account
    # No fire-and-forget nested DELETEs remain in the account block.
    assert "--method DELETE" not in block and "curl" not in block


def test_project_teardown_order_matches_arm_dependencies():
    text = SHELL.read_text(encoding="utf-8")
    order = [
        "--- AI Search ---",
        "sharedPrivateLinkResources",            # AI Search shared private links before the service
        "aif_delete foundry-children",           # Foundry project/account hosts and projects
        "Deleting AI Foundry V2 account",
        "# Step 5: Delete All Remaining Private Endpoints",
        "Pass 2/2: Deleting project subnets",
        "# Step 8: Delete Network Security Groups",
        'aif_delete group --confirm-resource-group "$projectResourceGroup"',
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_helper_cli_lists_foundry_children_action():
    args = deletion.arguments(["--subscription", "s", "--resource-group", "g", *CHILDREN])
    assert args.action == "foundry-children" and args.name == "foundry"


def caphost_gone(name="caphostproj"):
    """The live answer (aif-157, 2026-11-10, byor-157 run 42749009783): ARM puts the message in the HTTP reason, so
    az raises HTTPError(reason + '(' + body + ')') with no standard reason phrase and a UserError code."""
    message = f"CapabilityHost '{name}' not found in workspace 'foundry@proj1@AML'"
    return raw_error("ERROR: " + message + '({"error":{"code":"UserError","message":"' + message + '",'
                     '"details":[],"additionalInfo":[{"type":"ComponentName","info":{"value":"managementfrontend"}}]}})')


def test_project_caphost_not_found_user_error_is_absent_after_its_delete():
    status, runner, _ = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page(child(PROJECT))),
        ("GET", PROJECT_HOSTS, page(child(PROJECT_HOST))),
        ("GET", PROJECT_HOST, child(PROJECT_HOST)), ("DELETE", PROJECT_HOST, None),
        ("GET", PROJECT_HOST, caphost_gone()),
        ("GET", ACCOUNT_HOSTS, page()),
        ("GET", PROJECT, child(PROJECT)), ("DELETE", PROJECT, None), ("GET", PROJECT, error()),
        ("GET", PROJECTS, page()),
    ], CHILDREN, timeout=30)
    assert status == 0
    assert [call[1] for call in runner.calls if call[0] == "DELETE"] == [PROJECT_HOST, PROJECT]


def test_project_caphost_listed_but_already_gone_needs_no_delete():
    status, runner, _ = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page(child(PROJECT))),
        ("GET", PROJECT_HOSTS, page(child(PROJECT_HOST))),
        ("GET", PROJECT_HOST, caphost_gone()),
        ("GET", ACCOUNT_HOSTS, page()),
        ("GET", PROJECT, child(PROJECT)), ("DELETE", PROJECT, None), ("GET", PROJECT, error()),
        ("GET", PROJECTS, page()),
    ], CHILDREN, timeout=30)
    assert status == 0
    assert [call[1] for call in runner.calls if call[0] == "DELETE"] == [PROJECT]


def test_user_error_not_found_is_absence_only_for_capability_hosts():
    # The same text on another resource type stays a failure: absence is never inferred more widely.
    status, runner, _ = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page(child(PROJECT))),
        ("GET", PROJECT_HOSTS, page()),
        ("GET", ACCOUNT_HOSTS, page()),
        ("GET", PROJECT, caphost_gone()),
    ], CHILDREN, timeout=30)
    assert status != 0
    assert not any(call[0] == "DELETE" for call in runner.calls)


def test_a_caphost_user_error_that_is_not_not_found_still_fails():
    status, _, _ = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("GET", PROJECTS, page(child(PROJECT))),
        ("GET", PROJECT_HOSTS, page(child(PROJECT_HOST))),
        ("GET", PROJECT_HOST, raw_error('ERROR: Bad things({"error":{"code":"UserError","message":"Quota exceeded"}})')),
    ], CHILDREN, timeout=30)
    assert status != 0


ACCOUNT = ["resource", "--resource-type", "Microsoft.CognitiveServices/accounts", "--name", "foundry"]
NESTED = ("Cannot delete resource while nested resources exist. Some existing nested resource IDs include: "
          "'Microsoft.CognitiveServices/accounts/foundry/projects/proj1'.")


def test_account_delete_waits_out_a_project_arm_still_lists_as_nested():
    """aif-157 (byor-157 run 42751438602, 2026-11-10): the project GET answered 404 and the list was empty, but the
    account DELETE right after was refused with CannotDeleteResource for that project; minutes later it was gone."""
    status, runner, clock = invoke([
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("DELETE", FOUNDRY_ID, error("CannotDeleteResource", NESTED)),
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        *[step for _ in range(4) for step in (
            ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
            ("DELETE", FOUNDRY_ID, error("CannotDeleteResource", NESTED)),
            ("GET", FOUNDRY_ID, body(FOUNDRY_ID)))],
        ("GET", FOUNDRY_ID, body(FOUNDRY_ID)),
        ("DELETE", FOUNDRY_ID, None),
        ("GET", FOUNDRY_ID, error()),
    ], ACCOUNT, timeout=600)
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 6


def test_nested_refusal_is_bounded_and_then_fails():
    from unit.test_project_deletion_lifecycle import deletion as module

    attempts = module.NESTED_DELETE_ATTEMPTS
    assert 10 <= attempts <= 40  # minutes of patience at the 15 s service poll, never unbounded
    refused = ("DELETE", FOUNDRY_ID, error("CannotDeleteResource", NESTED))
    steps = [("GET", FOUNDRY_ID, body(FOUNDRY_ID))]
    steps += [refused, ("GET", FOUNDRY_ID, body(FOUNDRY_ID)), ("GET", FOUNDRY_ID, body(FOUNDRY_ID))] * (attempts - 1)
    steps += [refused, ("GET", FOUNDRY_ID, body(FOUNDRY_ID))]
    status, runner, _ = invoke(steps, ACCOUNT, timeout=3600)
    assert status != 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == attempts


def test_nested_refusal_is_not_retried_for_other_resource_types():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body(DBX_ID)),
        ("DELETE", DBX_ID, error("CannotDeleteResource", "Cannot delete resource while nested resources exist.")),
    ], RESOURCE, timeout=600)
    assert status != 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1
