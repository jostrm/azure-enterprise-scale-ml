"""Offline deletion-boundary tests; never call the real Azure CLI."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "environment_setup/aifactory/bicep/scripts/cleanup-project-orphan-roles.py"
spec = importlib.util.spec_from_file_location("project_orphan_roles", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def guid(number: int) -> str:
    return str(uuid.UUID(int=number))


def response(payload: object = None, error: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 1 if error else 0, json.dumps(payload), error)


NOT_FOUND = response(error='ERROR: Not Found({"error":{"code":"Request_ResourceNotFound"}})')
ARM_NOT_FOUND = response(error='ERROR: {"error":{"code":"ResourceNotFound"}}')
FORBIDDEN = response(error='ERROR: {"error":{"code":"Authorization_RequestDenied"}}')
CONFIG = module.Config(
    guid(1), "017", "vaip-esml-project017-sdc-dev-002-rg",
    "vaip-aifactory-esml-common-sdc-dev-002",
)
IDENTITY_NAME = "mi-prj017-sdc-dev-x46jf55f68002a6-001"


def identity_record(principal: str, name: str = IDENTITY_NAME, rg: str = CONFIG.project_rg) -> dict:
    return {
        "principalId": principal, "name": name,
        "resourceId": f"{CONFIG.scope(rg)}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{name}",
    }


def assignment(number: int, principal: str, scope: str) -> dict:
    return {
        "id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/{guid(number)}",
        "principalId": principal, "scope": scope, "principalName": "", "principalType": "Unknown",
    }


def group_assignment(number: int, principal: str, scope: str) -> dict:
    return assignment(number, principal, scope) | {
        "principalType": "Group", "principalName": "Research Team",
    }


class FakeAz:
    def __init__(self) -> None:
        self.records: dict[str, list] = {CONFIG.project_rg: [], CONFIG.common_rg: []}
        self.exists: dict[str, bool] = {CONFIG.project_rg: True, CONFIG.common_rg: True}
        self.history: object = []
        self.live: dict[str, subprocess.CompletedProcess[str]] = {}
        self.live_sequences: dict[str, list[subprocess.CompletedProcess[str]]] = {}
        self.typed: dict[str, subprocess.CompletedProcess[str]] = {}
        self.deleted: dict[str, subprocess.CompletedProcess[str]] = {}
        self.identities: dict[str, subprocess.CompletedProcess[str]] = {}
        self.assignment_reads: dict[str, subprocess.CompletedProcess[str]] = {}
        self.observed_assignments: dict[str, dict] = {}
        self.list_error: str | None = None
        self.delete_error = False
        self.pages: dict[str, subprocess.CompletedProcess[str]] = {}
        self.calls: list[tuple[str, ...]] = []
        self.deleted_ids: list[str] = []

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[:2] == ("group", "exists"):
            return response(self.exists[args[args.index("--name") + 1]])
        if args[:3] == ("deployment", "group", "list"):
            assert args[args.index("--resource-group") + 1] == CONFIG.project_rg
            if isinstance(self.history, subprocess.CompletedProcess):
                return self.history
            return response(self.history)
        if args[0] == "rest":
            url = args[args.index("--url") + 1]
            if url in self.pages:
                page = self.pages[url]
                if page.returncode == 0:
                    for raw in json.loads(page.stdout).get("value", []):
                        self.observed_assignments[raw["id"].lower()] = raw
                return page
            if url.startswith("https://management.azure.com/"):
                resource_id = url.removeprefix("https://management.azure.com").split("?")[0]
                if "/userassignedidentities/" in resource_id.lower():
                    return self.identities.get(resource_id.lower(), ARM_NOT_FOUND)
                if "/roleassignments/" in resource_id.lower():
                    if resource_id.lower() in self.assignment_reads:
                        return self.assignment_reads[resource_id.lower()]
                    return response(self.observed_assignments.get(resource_id.lower()))
                rg = url.split("/resourceGroups/")[1].split("/")[0]
                if rg == self.list_error:
                    return FORBIDDEN
                records = [
                    {"id": row["id"], "properties": {k: v for k, v in row.items() if k != "id"}}
                    if isinstance(row, dict) else row for row in self.records[rg]
                ]
                for raw in records:
                    if isinstance(raw, dict):
                        self.observed_assignments[raw["id"].lower()] = raw
                return response({"value": records})
            principal = url.rsplit("/", 1)[-1]
            if "/directoryObjects/" in url:
                if principal in self.live_sequences and self.live_sequences[principal]:
                    return self.live_sequences[principal].pop(0)
                return self.live.get(principal, NOT_FOUND)
            if "/groups/" in url or "/servicePrincipals/" in url:
                return self.typed.get(principal, NOT_FOUND)
            if "/directory/deletedItems/" in url:
                return self.deleted.get(principal, NOT_FOUND)
        if args[:3] == ("role", "assignment", "delete"):
            self.deleted_ids.append(args[args.index("--ids") + 1])
            return FORBIDDEN if self.delete_error else response()
        raise AssertionError(f"Unexpected CLI invocation: {args}")


class TestProjectOrphanRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.az = FakeAz()
        self.project_scope = CONFIG.scope(CONFIG.project_rg)
        self.common_scope = CONFIG.scope(CONFIG.common_rg)

    def clean(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            count = module.cleanup(CONFIG, self.az)
        self.output = output.getvalue()
        return count

    def test_only_deleted_project017_mi_and_discovered_group_in_both_rgs(self) -> None:
        mi, other_mi, live_mi, unknown = guid(3), guid(4), guid(5), guid(6)
        self.az.history = [
            identity_record(mi),
            identity_record(live_mi),
            identity_record(other_mi, "mi-prj018-sdc-dev-salt-001"),
        ]
        self.az.live[live_mi] = response({"id": live_mi})
        expected = []
        for offset, rg in enumerate((CONFIG.project_rg, CONFIG.common_rg)):
            scope = CONFIG.scope(rg)
            rows = [
                assignment(100 + offset * 10, mi, scope),
                group_assignment(101 + offset * 10, guid(2), scope),
                assignment(102 + offset * 10, other_mi, scope),
                assignment(103 + offset * 10, live_mi, scope),
                assignment(104 + offset * 10, unknown, scope),
            ]
            self.az.records[rg] = rows
            expected.extend(row["id"] for row in rows[:2])
        self.assertEqual(4, self.clean())
        self.assertCountEqual(expected, self.az.deleted_ids)
        self.assertIn("Cannot prove", self.output)

    def test_live_group_with_empty_principal_name_is_never_orphan(self) -> None:
        self.az.records[CONFIG.project_rg] = [
            group_assignment(99, guid(2), self.project_scope) | {"principalName": ""},
        ]
        self.az.records[CONFIG.common_rg] = [assignment(100, guid(2), self.common_scope)]
        self.az.live[guid(2)] = response({"id": guid(2), "displayName": None})
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)

    def test_single_rg_group_with_multiple_roles_matches_common_by_id_not_name(self) -> None:
        principal = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        direct = [
            group_assignment(100, principal, self.project_scope),
            group_assignment(101, principal.upper(), self.project_scope.upper()),
        ]
        common = group_assignment(102, principal, self.common_scope) | {"principalName": ""}
        unrelated = group_assignment(103, guid(9), self.common_scope) | {"principalName": "Research Team"}
        self.az.records[CONFIG.project_rg] = direct
        self.az.records[CONFIG.common_rg] = [common, unrelated]
        self.assertEqual(3, self.clean())
        self.assertCountEqual([row["id"] for row in (*direct, common)], self.az.deleted_ids)
        self.assertNotIn("Expected one distinct", self.output)

    def test_child_and_inherited_groups_do_not_count_as_project_rg_group(self) -> None:
        direct = group_assignment(100, guid(2), self.project_scope)
        child = group_assignment(101, guid(3), self.project_scope + "/providers/Microsoft.Storage/storageAccounts/prj")
        inherited = group_assignment(102, guid(4), f"/subscriptions/{CONFIG.subscription}")
        self.az.records[CONFIG.project_rg] = [direct, child, inherited]
        common = group_assignment(103, guid(2), self.common_scope)
        self.az.records[CONFIG.common_rg] = [
            common, group_assignment(104, guid(3), self.common_scope),
            group_assignment(105, guid(4), self.common_scope),
        ]
        self.assertEqual(2, self.clean())
        self.assertCountEqual([direct["id"], common["id"]], self.az.deleted_ids)

    def test_zero_or_multiple_rg_groups_preserves_groups_but_keeps_mi_cleanup(self) -> None:
        mi = assignment(110, guid(5), self.common_scope)
        for direct in (
            [],
            [group_assignment(100, guid(2), self.project_scope),
             group_assignment(101, guid(3), self.project_scope)],
        ):
            with self.subTest(groups=len(direct)):
                self.az = FakeAz()
                self.az.history = [identity_record(guid(5))]
                self.az.records[CONFIG.project_rg] = direct
                self.az.records[CONFIG.common_rg] = [
                    group_assignment(102, guid(2), self.common_scope), mi,
                ]
                self.assertEqual(1, self.clean())
                self.assertEqual([mi["id"]], self.az.deleted_ids)
                self.assertIn(f"found {len(direct)}", self.output)

    def test_group_discovery_does_not_use_configuration_names_or_unknown_types(self) -> None:
        self.az.records[CONFIG.project_rg] = [
            assignment(100, guid(2), self.project_scope) | {"principalName": "Project 017 Security"},
        ]
        self.az.records[CONFIG.common_rg] = [group_assignment(101, guid(2), self.common_scope)]
        with patch.dict(os.environ, {"ORPHAN_PROJECT_ENTRA_IDS": guid(2)}):
            self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)
        self.assertIn("found 0", self.output)

    def test_lookup_failures_and_non_structured_notfound_never_delete(self) -> None:
        self.az.records[CONFIG.project_rg] = [group_assignment(99, guid(2), self.project_scope)]
        self.az.records[CONFIG.common_rg] = [assignment(100, guid(2), self.common_scope)]
        for error in (
            FORBIDDEN,
            response(error="429 Too Many Requests"),
            response(error="Request_ResourceNotFound"),
            response(error="404 proxy not found"),
            response(error='{"error":{"code":"Denied","message":"Request_ResourceNotFound"}}'),
            response(error="Timed out"),
        ):
            with self.subTest(error=error.stderr):
                self.az.live[guid(2)] = error
                self.assertEqual(0, self.clean())
                self.assertEqual([], self.az.deleted_ids)

    def test_scopes_ids_and_project_number_boundaries(self) -> None:
        self.az.history = [identity_record(guid(2))]
        valid = assignment(100, guid(2), self.common_scope + "/providers/Microsoft.Storage/storageAccounts/lake")
        other_project = CONFIG.scope(CONFIG.project_rg.replace("017", "018"))
        inherited = f"/subscriptions/{CONFIG.subscription}"
        rows = [
            valid,
            assignment(101, guid(2), other_project),
            assignment(102, guid(2), inherited),
            assignment(103, guid(2), self.common_scope + "-other"),
            assignment(104, guid(2), self.project_scope + "0"),
            assignment(105, guid(2), self.project_scope) | {"id": assignment(106, guid(2), other_project)["id"]},
            assignment(107, "not-a-guid", self.common_scope),
            assignment(108, guid(2), self.common_scope) | {"id": "not-an-assignment-id"},
            assignment(109, guid(2), self.common_scope + "/../other-rg"),
            assignment(110, guid(2), self.common_scope + "/%2e%2e/other-rg"),
            assignment(111, guid(2), self.common_scope + "?other-rg"),
            None,
        ]
        self.az.records[CONFIG.common_rg] = rows
        self.assertEqual(1, self.clean())
        self.assertEqual([valid["id"]], self.az.deleted_ids)

    def test_identity_name_alone_or_other_project_history_cannot_establish_ownership(self) -> None:
        for number, name in enumerate(("mi-prj0170-sdc-dev-salt", "mi-prj018-sdc-dev-salt", "other-017")):
            principal = guid(10 + number)
            self.az.history.append(identity_record(principal, name))
            self.az.records[CONFIG.common_rg].append(
                assignment(100 + number, principal, self.common_scope) | {"principalName": IDENTITY_NAME}
            )
        principal = guid(20)
        self.az.history.append(identity_record(principal, IDENTITY_NAME, CONFIG.project_rg.replace("017", "018")))
        self.az.records[CONFIG.common_rg].append(assignment(120, principal, self.common_scope))
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)

    def test_soft_deleted_mi_requires_matching_principal_and_project_resource_id(self) -> None:
        principal = guid(3)
        row = assignment(100, principal, self.common_scope)
        self.az.records[CONFIG.common_rg] = [row]
        deleted = {
            "id": principal, "@odata.type": "#microsoft.graph.servicePrincipal",
            "displayName": IDENTITY_NAME,
            "alternativeNames": [identity_record(principal)["resourceId"]],
        }
        self.az.deleted[principal] = response(deleted | {"id": guid(99)})
        self.assertEqual(0, self.clean())
        self.az.deleted[principal] = response(deleted | {"alternativeNames": []})
        self.assertEqual(0, self.clean())
        self.az.deleted[principal] = response(deleted)
        self.assertEqual(1, self.clean())
        self.assertEqual([row["id"]], self.az.deleted_ids)

    def test_missing_project_rg_preserves_common_group_roles(self) -> None:
        self.az.exists[CONFIG.project_rg] = False
        row = group_assignment(100, guid(2), self.common_scope)
        self.az.records[CONFIG.common_rg] = [row]
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)
        self.assertIn("found 0", self.output)

    def test_failed_enumeration_prevents_all_deletions(self) -> None:
        self.az.records[CONFIG.project_rg] = [assignment(100, guid(2), self.project_scope)]
        self.az.list_error = CONFIG.common_rg
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)

    def test_all_pages_are_read_before_deleting_and_invalid_continuation_is_rejected(self) -> None:
        self.az.history = [identity_record(guid(2))]
        first = f"https://management.azure.com{self.common_scope}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01"
        second = first + "&$skiptoken=page2"
        row = assignment(100, guid(2), self.common_scope)
        arm = {"id": row["id"], "properties": {k: v for k, v in row.items() if k != "id"}}
        self.az.pages[first] = response({"value": [], "nextLink": second})
        self.az.pages[second] = response({"value": [arm]})
        self.assertEqual(1, self.clean())
        self.assertEqual([row["id"]], self.az.deleted_ids)
        self.az.deleted_ids.clear()
        for next_link in (first, "https://example.com/roles", None):
            with self.subTest(next_link=next_link):
                self.az.pages[second] = response({"value": [arm], "nextLink": next_link})
                self.assertEqual(0, self.clean())
                self.assertEqual([], self.az.deleted_ids)

    def test_missing_history_preserves_unattributed_mi(self) -> None:
        self.az.history = FORBIDDEN
        self.az.records[CONFIG.common_rg] = [assignment(100, guid(3), self.common_scope)]
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)

    def test_both_managed_identities_and_optional_sp_are_project_bound_in_both_rgs(self) -> None:
        for sp in (None, guid(7)):
            with self.subTest(optional_sp=sp):
                self.az = FakeAz()
                mi, aca = guid(3), guid(4)
                self.az.history = [
                    identity_record(mi),
                    identity_record(aca, "mi-aca-prj017-sdc-dev-salt-001"),
                    {
                        "deploymentName": f"08b-spAndMI2Array-{CONFIG.project_rg}"[:64],
                        "spAndMiArray": [sp, mi] if sp else [mi],
                    },
                    {
                        "deploymentName": f"08b-spAndMI2Array-{CONFIG.project_rg.replace('017', '018')}"[:64],
                        "spAndMiArray": [guid(8)],
                    },
                ]
                principals = [mi, aca] + ([sp] if sp else [])
                expected = []
                for index, rg in enumerate((CONFIG.project_rg, CONFIG.common_rg)):
                    rows = [assignment(200 + index * 10 + i, p, CONFIG.scope(rg)) for i, p in enumerate(principals)]
                    expected.extend(row["id"] for row in rows)
                    self.az.records[rg] = rows + [assignment(209 + index * 10, guid(8), CONFIG.scope(rg))]
                self.assertEqual(len(expected), self.clean())
                self.assertCountEqual(expected, self.az.deleted_ids)

    def test_null_sp_or_malformed_history_never_introduces_wildcard_ownership(self) -> None:
        self.az.history = [
            {"deploymentName": f"08-spAndMI2Array-{CONFIG.project_rg}"[:64], "spAndMiArray": None},
            {"deploymentName": f"08b-spAndMI2Array-{CONFIG.project_rg}"[:64], "spAndMiArray": [None, guid(3)]},
        ]
        self.az.records[CONFIG.common_rg] = [
            assignment(100, guid(3), self.common_scope), assignment(101, guid(4), self.common_scope),
        ]
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)

    def test_optional_sp_deleted_metadata_requires_project_token_and_project_assignment(self) -> None:
        principal = guid(7)
        direct = assignment(100, principal, self.project_scope)
        common = assignment(101, principal, self.common_scope)
        self.az.records[CONFIG.common_rg] = [common]
        deleted = {
            "id": principal, "@odata.type": "#microsoft.graph.servicePrincipal",
            "servicePrincipalType": "Application", "displayName": "sp-team-prj017-dev",
        }
        self.az.deleted[principal] = response(deleted)
        self.assertEqual(0, self.clean())
        self.az.records[CONFIG.project_rg] = [direct]
        for name in (None, "", "sp-team-prj0170-dev", "sp-team-prj018-dev", "sp-team-017"):
            with self.subTest(name=name):
                self.az.deleted[principal] = response(deleted | {"displayName": name})
                self.assertEqual(0, self.clean())
        self.az.deleted[principal] = response(deleted)
        self.assertEqual(2, self.clean())
        self.assertCountEqual([direct["id"], common["id"]], self.az.deleted_ids)

    def test_live_shared_team_group_never_removed_even_if_later_lookup_would_fail(self) -> None:
        other_scope = self.project_scope.replace("017", "018")
        self.az.records[CONFIG.project_rg] = [
            group_assignment(100, guid(2), self.project_scope),
            group_assignment(101, guid(2), self.project_scope),
            group_assignment(102, guid(2), other_scope),
        ]
        self.az.records[CONFIG.common_rg] = [
            group_assignment(103, guid(2), self.common_scope),
            group_assignment(104, guid(2), self.common_scope + "/providers/Microsoft.Storage/storageAccounts/lake"),
        ]
        self.az.live_sequences[guid(2)] = [response({"id": guid(2)}), NOT_FOUND]
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)
        self.assertEqual([NOT_FOUND], self.az.live_sequences[guid(2)])
        self.assertIn("already observed live", self.output)

    def test_independent_final_lookup_preserves_live_group_and_on_any_error(self) -> None:
        self.az.records[CONFIG.project_rg] = [group_assignment(100, guid(2), self.project_scope)]
        self.az.records[CONFIG.common_rg] = [group_assignment(101, guid(2), self.common_scope)]
        for result in (
            response({"id": guid(2)}), FORBIDDEN,
            response(error="429 Too Many Requests"), response(error="404 gateway missing"),
            response(error="Request_ResourceNotFound"), response(error="Timed out"),
        ):
            with self.subTest(result=result):
                self.az.typed[guid(2)] = result
                self.assertEqual(0, self.clean())
                self.assertEqual([], self.az.deleted_ids)
                self.assertIn("Final orphan check", self.output)

    def test_assignment_recheck_rejects_changes_and_read_failures(self) -> None:
        self.az.history = [identity_record(guid(3))]
        row = assignment(100, guid(3), self.common_scope) | {"condition": "Team"}
        self.az.records[CONFIG.common_rg] = [row]
        raw = {"id": row["id"], "properties": {key: value for key, value in row.items() if key != "id"}}
        variants = [FORBIDDEN, NOT_FOUND, response(None)]
        for key, value in (
            ("scope", self.project_scope.replace("017", "018")),
            ("principalId", guid(9)), ("principalType", "Group"), ("roleDefinitionId", "different-role"),
            ("condition", "new-condition"), ("condition", "team"),
        ):
            variants.append(response(raw | {"properties": raw["properties"] | {key: value}}))
        for result in variants:
            with self.subTest(result=result):
                self.az.assignment_reads[row["id"].lower()] = result
                self.assertEqual(0, self.clean())
                self.assertEqual([], self.az.deleted_ids)
                self.assertIn("Assignment changed or could not be re-read", self.output)

    def test_conflicting_duplicate_assignment_aborts_before_any_deletion(self) -> None:
        row = group_assignment(100, guid(2), self.project_scope)
        self.az.records[CONFIG.project_rg] = [row]
        self.az.records[CONFIG.common_rg] = [
            group_assignment(101, guid(2), self.common_scope), row | {"principalId": guid(9)},
        ]
        self.assertEqual(0, self.clean())
        self.assertEqual([], self.az.deleted_ids)
        self.assertIn("changed during enumeration", self.output)

    def test_arm_live_managed_identity_preserved_despite_directory_notfound(self) -> None:
        principal = guid(3)
        record = identity_record(principal)
        self.az.history = [record]
        row = assignment(100, principal, self.common_scope)
        self.az.records[CONFIG.common_rg] = [row]
        for result in (
            response({"id": record["resourceId"], "properties": {"principalId": principal}}),
            FORBIDDEN, response(None), response({"id": record["resourceId"], "properties": {}}),
            response(error="404 gateway missing"),
        ):
            with self.subTest(result=result):
                self.az.identities[record["resourceId"].lower()] = result
                self.assertEqual(0, self.clean())
                self.assertEqual([], self.az.deleted_ids)
        # Recreated identity has a different principal; only the old, Graph-confirmed orphan is removed.
        self.az.identities[record["resourceId"].lower()] = response({
            "id": record["resourceId"], "properties": {"principalId": guid(9)},
        })
        self.assertEqual(1, self.clean())
        self.assertEqual([row["id"]], self.az.deleted_ids)

    def test_every_delete_is_exact_id_after_assignment_and_typed_principal_rechecks(self) -> None:
        self.az.history = [identity_record(guid(3))]
        self.az.records[CONFIG.common_rg] = [assignment(100, guid(3), self.common_scope)]
        self.assertEqual(1, self.clean())
        deletion_index = next(i for i, call in enumerate(self.az.calls) if call[:3] == ("role", "assignment", "delete"))
        deletion = self.az.calls[deletion_index]
        self.assertIn("--ids", deletion)
        self.assertNotIn("--scope", deletion)
        self.assertNotIn("--resource-group", deletion)
        preceding = self.az.calls[deletion_index - 2:deletion_index]
        urls = [call[call.index("--url") + 1] for call in preceding]
        self.assertIn("/roleAssignments/", urls[0])
        self.assertIn("/servicePrincipals/", urls[1])

    def test_duplicate_ids_case_insensitive_and_failed_delete_not_counted(self) -> None:
        self.az.history = [identity_record(guid(2))]
        row = assignment(100, guid(2), self.common_scope)
        self.az.records[CONFIG.common_rg] = [row, row | {"id": row["id"].upper(), "scope": self.common_scope.upper()}]
        self.az.delete_error = True
        self.assertEqual(0, self.clean())
        self.assertEqual(1, len(self.az.deleted_ids))
        self.assertIn("Failed to delete", self.output)

    def test_configuration_uses_exact_project_and_common_override(self) -> None:
        env = {
            "ORPHAN_SUBSCRIPTION_ID": guid(1), "ORPHAN_PROJECT_NUMBER": "017",
            "ORPHAN_LOCATION_SUFFIX": "sdc", "ORPHAN_ENV": "dev",
            "ORPHAN_RG_PREFIX": "vaip-", "ORPHAN_RG_SUFFIX": "-002",
            "ORPHAN_PROJECT_PREFIX": "esml-", "ORPHAN_PROJECT_SUFFIX": "-rg",
            "ORPHAN_COMMON_RG": CONFIG.common_rg,
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(CONFIG, module.Config.from_env())
        with patch.dict(os.environ, env | {"ORPHAN_COMMON_RG": "$(commonResourceGroup_param)"}, clear=True):
            self.assertEqual("vaip-esml-common-sdc-dev-002", module.Config.from_env().common_rg)
        for key, value in (
            ("ORPHAN_PROJECT_NUMBER", "17"), ("ORPHAN_SUBSCRIPTION_ID", "$(dev_test_prod_sub_id)"),
            ("ORPHAN_PROJECT_PREFIX", "../"),
        ):
            with self.subTest(key=key), patch.dict(os.environ, env | {key: value}, clear=True):
                with self.assertRaises(ValueError):
                    module.Config.from_env()

    def test_cli_launcher_preserves_arguments_without_cmd_shell(self) -> None:
        executable = r"C:\AzureCLI\wbin\az.cmd" if os.name == "nt" else "/usr/bin/az"
        url = "https://management.azure.com/roles?api-version=2022-04-01&$skiptoken=page2"
        def invoke(config, az):
            self.assertEqual(CONFIG, config)
            az("rest", "--url", url)
        with (
            patch.object(module.Config, "from_env", return_value=CONFIG),
            patch.object(module.shutil, "which", return_value=executable),
            patch.object(module.Path, "is_file", return_value=True),
            patch.object(module, "cleanup", side_effect=invoke),
            patch.object(module.subprocess, "run", return_value=response()) as run,
        ):
            module.main()
        args, kwargs = run.call_args
        self.assertEqual(url, args[0][-1])
        self.assertFalse(kwargs.get("shell", False))
        if os.name == "nt":
            self.assertTrue(args[0][0].endswith("python.exe"))
            self.assertEqual(["-IBm", "azure.cli"], args[0][1:3])


if __name__ == "__main__":
    unittest.main()
