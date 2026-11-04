"""Read-only Graph delta, hierarchy, permission and binary transport contracts."""
from copy import deepcopy
import base64
from io import BytesIO
import json
import time
import unittest
from urllib.error import HTTPError

from sales_demo.graph_delta import (
    BinaryGraphTransport, GraphDeltaClient, GraphSyncError, IncompleteInventory,
    PREFER, build_change_plan, permission_fingerprint, project_permissions,
    reconcile_inventory, validate_graph_config,
)


TENANT = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
GROUP = "33333333-3333-3333-3333-333333333333"
DELTA = "https://graph.microsoft.com/v1.0/drives/drive-1/root/delta"
ITEMS = "https://graph.microsoft.com/v1.0/drives/drive-1/items/"


def scan_token(scopes="Sites.FullControl.All"):
    payload = {"tid": TENANT, "aud": "https://graph.microsoft.com", "scp": scopes, "exp": time.time() + 3600}
    return "header." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".signature"


def config():
    return {
        "tenant_id": TENANT, "drive_id": "drive-1", "drive_type": "documentLibrary",
        "scope_id": "synthetic-sales", "bindings": [
            {"partition": "json", "item_id": "json-id"},
            {"partition": "excel", "item_id": "excel-id"},
        ],
        "download_hosts": ["contoso.sharepoint.com"],
        "permission_scan_approved": True,
        "source_read_scope": "Sites.FullControl.All",
        "source_authorization": "Operator approved only these two synthetic source files.",
        "principal_map": {f"user:{USER}": USER, f"group:{GROUP}": GROUP},
    }


def grant(identity=GROUP, kind="group", roles=None):
    return {"id": "permission-" + identity, "roles": roles or ["read"],
            "grantedToV2": {kind: {"id": identity, "displayName": "Approved reader"}}}


def item(identity, *, parent="folder", name=None, etag="e1", folder=False):
    return {"id": identity, "name": name or identity,
            "parentReference": {"id": parent, "driveId": "drive-1"},
            "eTag": etag, "folder" if folder else "file": {}}


def inventory():
    return {"root": {"id": "root", "name": "root", "root": {}, "folder": {}},
            "folder": item("folder", parent="root", folder=True),
            "json-id": item("json-id"), "excel-id": item("excel-id")}


class FakeTransport:
    def __init__(self, replies=(), binary=()):
        self.replies = list(replies)
        self.binary = list(binary)
        self.calls = []

    def request(self, method, url, *, audience, headers):
        self.calls.append((method, url, audience, headers))
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    def request_bytes(self, method, url, *, audience, headers, max_bytes):
        self.calls.append((method, url, audience, headers))
        response = self.binary.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class GraphDeltaTests(unittest.TestCase):
    def test_odata_token_continuation_is_preserved_within_exact_drive_root(self):
        cursor = DELTA + "(token='opaque%2Btoken')"
        transport = FakeTransport([{"value": [], "@odata.deltaLink": cursor}])
        self.assertEqual(GraphDeltaClient(config(), transport).fetch(cursor)["delta_link"], cursor)
        self.assertEqual(transport.calls[0][1], cursor)

    def test_follows_empty_opaque_pages_and_last_occurrence_wins(self):
        next_url = DELTA + "?$skiptoken=a%2Bb%3D&x=1"
        empty_url = DELTA + "?$skiptoken=empty"
        cursor = DELTA + "?$deltatoken=final%2Fopaque"
        first = item("json-id", name="old.json")
        last = item("json-id", name="arbitrary-new.json", etag="e2")
        last["@microsoft.graph.sharedChanged"] = "True"
        transport = FakeTransport([
            {"value": [first], "@odata.nextLink": next_url},
            {"value": [], "@odata.nextLink": empty_url},
            {"value": [last], "@odata.deltaLink": cursor},
        ])
        result = GraphDeltaClient(config(), transport).fetch()
        self.assertEqual(result["items"], [{**last, "@microsoft.graph.sharedChanged": True}])
        self.assertEqual(result["delta_link"], cursor)
        self.assertTrue(result["full_resync"])
        self.assertEqual([call[1] for call in transport.calls], [DELTA, next_url, empty_url])
        self.assertTrue(all(call[0] == "GET" and call[2] == "https://graph.microsoft.com"
                            and call[3]["Prefer"] == PREFER for call in transport.calls))

    def test_incremental_cursor_and_tombstone_last_wins(self):
        cursor = DELTA + "?token=opaque"
        transport = FakeTransport([{
            "value": [item("json-id"), {"id": "json-id", "deleted": {}}],
            "@odata.deltaLink": DELTA + "?token=next",
        }])
        result = GraphDeltaClient(config(), transport).fetch(cursor)
        self.assertFalse(result["full_resync"])
        self.assertEqual(result["items"], [{"id": "json-id", "deleted": {}}])

    def test_410_both_resync_codes_restart_source_authoritative_inventory(self):
        for code in ("resyncChangesApplyDifferences", "resyncChangesUploadDifferences"):
            location = DELTA + "?token=recovery%2Bvalue"
            error = HTTPError(DELTA, 410, "Gone", {"Location": location},
                              BytesIO(json.dumps({"error": {"code": code}}).encode()))
            transport = FakeTransport([
                {"value": [item("stale")], "@odata.nextLink": DELTA + "?page=2"},
                error,
                {"value": [item("fresh")], "@odata.deltaLink": DELTA + "?token=new"},
            ])
            result = GraphDeltaClient(config(), transport).fetch(DELTA + "?token=old")
            self.assertTrue(result["full_resync"])
            self.assertEqual([entry["id"] for entry in result["items"]], ["fresh"])
            self.assertEqual(transport.calls[-1][1], location)
            self.assertTrue(all(call[0] == "GET" for call in transport.calls))

    def test_bad_links_and_latest_bootstrap_never_requested(self):
        bad_urls = [
            "https://attacker.example/v1.0/drives/drive-1/root/delta?secret=hidden",
            DELTA.replace("drive-1", "different"),
            DELTA.replace("https:", "http:"), DELTA + "/../children?x=1",
            DELTA.replace("graph.microsoft.com", "graph.microsoft.com:444"),
            DELTA.replace("graph.microsoft.com", "user@graph.microsoft.com"),
            DELTA + "#fragment", DELTA + "?token=latest", DELTA + "?%74oken=latest",
            DELTA + "\n?token=secret", DELTA + "(token='latest')",
        ]
        for url in bad_urls:
            with self.subTest(url=url):
                transport = FakeTransport()
                with self.assertRaises(GraphSyncError) as caught:
                    GraphDeltaClient(config(), transport).fetch(url)
                self.assertEqual(transport.calls, [])
                self.assertNotIn("secret", str(caught.exception))

    def test_continuation_cycle_page_budget_byte_budget_and_missing_cursor(self):
        for replies, changes in (
            ([{"value": [], "@odata.nextLink": DELTA}], {}),
            ([{"value": [], "@odata.nextLink": DELTA + "?page=2"}], {"max_pages": 1}),
            ([{"value": [{"id": "x", "name": "z" * 500}], "@odata.deltaLink": DELTA}],
             {"max_page_bytes": 128}),
            ([{"value": []}], {}),
            ([{"value": [], "@odata.deltaLink": DELTA, "@odata.nextLink": DELTA}], {}),
        ):
            settings = {**config(), **changes}
            with self.subTest(changes=changes), self.assertRaises(GraphSyncError):
                GraphDeltaClient(settings, FakeTransport(replies)).fetch()

    def test_invalid_config_and_foreign_drive_fail_closed(self):
        for change in (
            {"drive_type": "personal"}, {"bindings": [{"partition": "json", "item_id": "a"}]},
            {"download_hosts": ["*.sharepoint.com"]},
            {"download_hosts": ["127.0.0.1"]}, {"download_hosts": ["localhost"]},
            {"drive_id": "drive/../other"},
        ):
            with self.subTest(change=change), self.assertRaises(GraphSyncError):
                validate_graph_config({**config(), **change})
        foreign = item("json-id")
        foreign["parentReference"]["driveId"] = "other"
        with self.assertRaises(GraphSyncError):
            GraphDeltaClient(config(), FakeTransport([
                {"value": [foreign], "@odata.deltaLink": DELTA}])).fetch()

    def test_errors_never_expose_transport_urls_or_tokens(self):
        transport = FakeTransport([RuntimeError("Bearer secret https://host/?sig=secret")])
        with self.assertRaises(GraphSyncError) as caught:
            GraphDeltaClient(config(), transport).fetch()
        self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_inventory_compacts_secrets_and_propagates_folder_deletion(self):
        prior = inventory()
        changed = item("json-id", name="renamed.json")
        changed.update({"webUrl": "https://secret/?token=x",
                        "@microsoft.graph.downloadUrl": "https://secret/?sig=x"})
        changed["parentReference"]["path"] = "secret/path"
        folded = reconcile_inventory(prior, {"items": [changed], "full_resync": False})
        self.assertNotIn("secret", json.dumps(folded))
        deleted = reconcile_inventory(folded, {
            "items": [{"id": "folder", "deleted": {}}], "full_resync": False})
        self.assertEqual(set(deleted), {"root"})
        self.assertEqual(prior["json-id"]["name"], "json-id")

    def test_move_out_of_deleted_folder_survives_and_full_resync_drops_stale(self):
        folded = reconcile_inventory(inventory(), {
            "items": [item("json-id", parent="root"), {"id": "folder", "deleted": {}}],
            "full_resync": False})
        self.assertEqual(set(folded), {"root", "json-id"})
        root = inventory()["root"]
        self.assertEqual(reconcile_inventory(inventory(), {
            "items": [root], "full_resync": True}), {"root": root})

    def test_orphans_and_cycles_require_full_inventory(self):
        for changed in (item("json-id", parent="missing"), item("folder", parent="json-id", folder=True)):
            with self.subTest(changed=changed), self.assertRaises(IncompleteInventory):
                reconcile_inventory(inventory(), {"items": [changed], "full_resync": False})

    def test_change_plan_detects_ancestor_rename_and_unannotated_acl_changes(self):
        prior = inventory()
        current = reconcile_inventory(prior, {
            "items": [item("folder", parent="root", name="renamed", folder=True)],
            "full_resync": False})
        plan = build_change_plan(config(), prior, current,
                                 {"json-id": "a", "excel-id": "b"},
                                 {"json-id": "changed", "excel-id": "b"})
        self.assertEqual(plan["metadata_changed"], ["excel-id", "json-id"])
        self.assertEqual(plan["security_changed"], ["json-id"])
        self.assertEqual(plan["content_changed"], [])
        self.assertTrue(plan["complete"])
        deleted = build_change_plan(config(), prior, {"root": prior["root"]}, {}, {})
        self.assertFalse(deleted["complete"])
        self.assertEqual(deleted["deleted"], ["excel-id", "json-id"])

    def test_ancestor_sharing_annotation_affects_selected_descendants(self):
        prior = inventory()
        current = deepcopy(prior)
        current["folder"]["@microsoft.graph.sharedChanged"] = True
        hashes = {"json-id": "same", "excel-id": "same"}
        plan = build_change_plan(config(), prior, current, hashes, hashes)
        self.assertEqual(plan["security_changed"], ["excel-id", "json-id"])

    def test_unsupported_recovery_or_untrusted_recovery_location_blocks(self):
        for code, location in (
            ("unknownCode", DELTA + "?token=new"),
            ("resyncChangesApplyDifferences", "https://attacker.example/?token=secret"),
            ("resyncChangesUploadDifferences", None),
        ):
            headers = {"Location": location} if location else {}
            error = HTTPError(DELTA, 410, "Gone", headers,
                              BytesIO(json.dumps({"error": {"code": code}}).encode()))
            transport = FakeTransport([error])
            with self.subTest(code=code, location=location), self.assertRaises(GraphSyncError):
                GraphDeltaClient(config(), transport).fetch(DELTA + "?token=old")
            self.assertEqual(len(transport.calls), 1)

    def test_last_occurrence_restores_tombstone_and_round_does_not_retain_old_annotation(self):
        prior = inventory()
        prior["json-id"]["@microsoft.graph.sharedChanged"] = True
        folded = reconcile_inventory(prior, {
            "items": [{"id": "excel-id", "deleted": {}}, item("excel-id", etag="e2")],
            "full_resync": False})
        self.assertEqual(folded["excel-id"]["eTag"], "e2")
        self.assertNotIn("@microsoft.graph.sharedChanged", folded["json-id"])

    def test_source_scope_approval_required_before_any_read(self):
        for change in ({"permission_scan_approved": False}, {"source_authorization": ""}):
            transport = FakeTransport()
            with self.subTest(change=change), self.assertRaises(GraphSyncError):
                GraphDeltaClient({**config(), **change}, transport).fetch()
            self.assertEqual(transport.calls, [])


class PermissionTests(unittest.TestCase):
    def test_explicit_same_entra_projection_supports_user_group_and_roles(self):
        permissions = [grant(), grant(USER, "user", ["owner", "write"])]
        policy = project_permissions(config(), permissions)
        self.assertEqual(policy["allowed_group_ids"], [GROUP])
        self.assertEqual(policy["allowed_user_ids"], [USER])
        self.assertEqual(policy["permission_sha256"], permission_fingerprint(permissions))

    def test_typed_principal_map_preserves_both_entra_type_and_id(self):
        settings = config()
        settings["principal_map"] = {
            f"group:{GROUP}": {"type": "group", "id": GROUP},
            f"user:{USER}": {"type": "user", "id": USER},
        }
        policy = project_permissions(settings, [grant(), grant(USER, "user")])
        self.assertEqual(policy["allowed_group_ids"], [GROUP])
        self.assertEqual(policy["allowed_user_ids"], [USER])
        for target in (
            {"type": "user", "id": GROUP}, {"type": "group", "id": USER},
            {"type": "group", "id": GROUP, "unreviewed": True}, {"id": GROUP},
        ):
            with self.subTest(target=target), self.assertRaises(GraphSyncError):
                project_permissions({**settings, "principal_map": {f"group:{GROUP}": target}}, [grant()])

    def test_site_user_with_verified_user_is_not_flattened(self):
        permissions = [grant(USER, "user")]
        permissions[0]["grantedToV2"]["siteUser"] = {"id": "9", "loginName": "ignored"}
        self.assertEqual(project_permissions(config(), permissions)["allowed_user_ids"], [USER])

    def test_every_unsupported_or_unapproved_projection_fails(self):
        unsupported = [
            [], [{"id": "link", "roles": ["read"], "link": {"scope": "anonymous"}}],
            [{"id": "org", "roles": ["read"], "link": {"scope": "organization"}}],
            [{**grant(), "invitation": {"email": "nobody@example.test"}}],
            [{**grant(), "expirationDateTime": "2027-01-01T00:00:00Z"}],
            [grant(roles=["manage"])], [grant("5", "siteGroup")],
            [grant("7", "siteUser")], [grant("not-a-uuid", "user")],
            [{**grant(), "grantedToV2": {"application": {"id": USER}}}],
        ]
        for permissions in unsupported:
            with self.subTest(permissions=permissions), self.assertRaises(GraphSyncError):
                project_permissions(config(), permissions)
        for changes in (
            {"principal_map": {}}, {"principal_map": {f"group:{GROUP}": USER}},
            {"permission_scan_approved": False}, {"source_authorization": ""},
            {"source_read_scope": "Files.Read.All"},
        ):
            with self.subTest(changes=changes), self.assertRaises(GraphSyncError):
                project_permissions({**config(), **changes}, [grant()])

    def test_permission_fingerprint_excludes_volatile_urls_not_permission_metadata(self):
        first = [{**grant(), "inheritedFrom": {"id": "folder", "driveId": "drive-1",
                                             "path": "/drive/root:/parent",
                                             "webUrl": "https://x/?sig=one"}}]
        second = deepcopy(first)
        second[0]["inheritedFrom"]["webUrl"] = "https://x/?sig=two"
        self.assertEqual(permission_fingerprint(first), permission_fingerprint(second))
        second[0]["roles"] = ["write"]
        self.assertNotEqual(permission_fingerprint(first), permission_fingerprint(second))

    def test_permissions_paginated_bound_to_exact_selected_item(self):
        first_url = ITEMS + "json-id/permissions"
        second_url = first_url + "?$skiptoken=opaque%2Btoken"
        transport = FakeTransport([
            {"value": [grant()], "@odata.nextLink": second_url},
            {"value": [grant(USER, "user")]},
        ])
        client = GraphDeltaClient(config(), transport)
        self.assertEqual(len(client.permissions("json-id")), 2)
        self.assertEqual([entry[1] for entry in transport.calls], [first_url, second_url])
        with self.assertRaises(GraphSyncError):
            client.permissions("unbound-id")
        with self.assertRaises(GraphSyncError):
            client.metadata("unbound-id")

    def test_offpath_permission_continuation_rejected(self):
        transport = FakeTransport([{"value": [grant()],
                                    "@odata.nextLink": ITEMS + "excel-id/permissions"}])
        with self.assertRaises(GraphSyncError):
            GraphDeltaClient(config(), transport).permissions("json-id")
        self.assertEqual(len(transport.calls), 1)

    def test_permission_changes_in_v2_identity_arrays_are_fingerprinted(self):
        first = [{"id": "array", "roles": ["read"], "grantedToIdentitiesV2": [
            {"group": {"id": GROUP}}, {"user": {"id": USER}}]}]
        second = deepcopy(first)
        second[0]["grantedToIdentitiesV2"].reverse()
        self.assertEqual(permission_fingerprint(first), permission_fingerprint(second))
        self.assertEqual(project_permissions(config(), first)["allowed_user_ids"], [USER])
        second[0]["grantedToIdentitiesV2"].pop()
        self.assertNotEqual(permission_fingerprint(first), permission_fingerprint(second))

    def test_empty_continuation_is_not_completeness_evidence(self):
        transport = FakeTransport([{"value": [grant()], "@odata.nextLink": ""}])
        with self.assertRaises(GraphSyncError):
            GraphDeltaClient(config(), transport).permissions("json-id")


class ContentTests(unittest.TestCase):
    def test_content_redirect_has_no_graph_bearer_and_etag_checked(self):
        signed = "https://contoso.sharepoint.com/download?sig=do-not-store"
        transport = FakeTransport([item("json-id"), item("json-id")], [
            (302, {"Location": signed}, b""), (200, {}, b'{"records":[]}'),
        ])
        result = GraphDeltaClient(config(), transport).content("json-id", "e1")
        self.assertEqual(result, b'{"records":[]}')
        calls = [call for call in transport.calls if "/content" in call[1] or "?sig=" in call[1]]
        self.assertEqual(calls[0][2], "https://graph.microsoft.com")
        self.assertEqual(calls[1][2], None)
        self.assertEqual(calls[1][3], {})

    def test_foreign_signed_hosts_and_second_redirect_refused(self):
        for signed in (
            "https://contoso.sharepoint.com.attacker.example/?sig=secret",
            "http://contoso.sharepoint.com/?sig=secret",
            "https://contoso.sharepoint.com:444/?sig=secret",
            "https://user@contoso.sharepoint.com/?sig=secret",
            "https://127.0.0.1/?sig=secret",
        ):
            transport = FakeTransport([item("json-id")], [(302, {"Location": signed}, b"")])
            with self.subTest(signed=signed), self.assertRaises(GraphSyncError) as caught:
                GraphDeltaClient(config(), transport).content("json-id", "e1")
            self.assertEqual(len(transport.calls), 2)
            self.assertNotIn("secret", str(caught.exception))
        transport = FakeTransport([item("json-id")], [
            (302, {"Location": "https://contoso.sharepoint.com/?sig=1"}, b""),
            (302, {"Location": "https://contoso.sharepoint.com/?sig=2"}, b"")])
        with self.assertRaises(GraphSyncError):
            GraphDeltaClient(config(), transport).content("json-id", "e1")

    def test_etag_race_oversize_and_unbound_download_fail(self):
        for replies, body, settings in (
            ([item("json-id"), item("json-id", etag="changed")], b"valid", {}),
            ([item("json-id")], b"x" * 10, {"max_content_bytes": 8}),
        ):
            transport = FakeTransport(replies, [(200, {}, body)])
            with self.subTest(settings=settings), self.assertRaises(GraphSyncError):
                GraphDeltaClient({**config(), **settings}, transport).content("json-id", "e1")
        transport = FakeTransport()
        with self.assertRaises(GraphSyncError):
            GraphDeltaClient(config(), transport).content("outside", "e1")
        self.assertEqual(transport.calls, [])

    def test_inspection_always_refreshes_permissions_without_annotation(self):
        transport = FakeTransport()
        client = GraphDeltaClient(config(), transport)
        scanned = []
        client.metadata = lambda identity: item(identity)
        client.content = lambda identity, etag: b"raw"
        def permissions(identity):
            scanned.append(identity)
            return [grant()]
        client.permissions = permissions
        snapshots = client.inspect_selected(inventory())
        self.assertEqual(set(snapshots), {"json", "excel"})
        self.assertGreaterEqual(scanned.count("json-id"), 1)
        self.assertGreaterEqual(scanned.count("excel-id"), 1)
        self.assertEqual(snapshots["json"]["policy"]["allowed_group_ids"], [GROUP])
        with self.assertRaises(IncompleteInventory):
            client.inspect_selected({"json-id": item("json-id")})

    def test_inspection_accepts_fresh_metadata_enrichment_but_not_version_changes(self):
        client = GraphDeltaClient(config(), FakeTransport())
        client.metadata = lambda identity: {**item(identity), "size": 5}
        client.permissions = lambda identity: [grant()]
        client.content = lambda identity, etag: b"raw"
        self.assertEqual(client.inspect_selected(inventory())["json"]["item"]["size"], 5)
        client.metadata = lambda identity: item(identity, etag="new")
        with self.assertRaises(GraphSyncError):
            client.inspect_selected(inventory())

    def test_inspection_rejects_permission_race(self):
        client = GraphDeltaClient(config(), FakeTransport())
        client.metadata = lambda identity: item(identity)
        client.content = lambda identity, etag: b"raw"
        permissions = iter(([grant()], [grant(USER, "user")]))
        client.permissions = lambda identity: next(permissions)
        with self.assertRaises(GraphSyncError):
            client.inspect_selected(inventory())

    def test_remote_shortcut_and_package_cannot_be_source_files(self):
        for facet in ("remoteItem", "package"):
            transport = FakeTransport([{**item("json-id"), facet: {"id": "foreign"}}])
            with self.subTest(facet=facet), self.assertRaises(GraphSyncError):
                GraphDeltaClient(config(), transport).metadata("json-id")

    def test_native_transport_stream_bound_get_only_and_no_redirect_forwarding(self):
        class Credentials:
            tenant_id = TENANT
            def token(self, audience):
                self.audience = audience
                return scan_token()
        class Response:
            status = 200
            headers = {}
            def read(self, count):
                self.count = count
                return b"x" * count
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        class Opener:
            def open(self, request, timeout):
                self.request = request
                return Response()
        opener = Opener()
        native = BinaryGraphTransport(config(), Credentials(), opener=opener)
        with self.assertRaises(GraphSyncError):
            native.request_bytes("GET", ITEMS + "json-id/content",
                                 audience="https://graph.microsoft.com", headers={}, max_bytes=8)
        with self.assertRaises(GraphSyncError):
            native.request("POST", DELTA, audience="https://graph.microsoft.com", headers={})
        with self.assertRaises(GraphSyncError):
            native.request_bytes("GET", "https://contoso.sharepoint.com/?sig=x", audience=None,
                                 headers={"Authorization": "Bearer sensitive"}, max_bytes=8)

    def test_native_actual_redirect_is_returned_without_following_or_leaking(self):
        class Credentials:
            tenant_id = TENANT
            def token(self, audience):
                return scan_token()
        class Opener:
            calls = []
            def open(self, request, timeout):
                self.calls.append(request)
                raise HTTPError(request.full_url, 302, "Redirect",
                                {"Location": "https://contoso.sharepoint.com/?sig=hidden"},
                                BytesIO(b""))
        opener = Opener()
        native = BinaryGraphTransport(config(), Credentials(), opener=opener)
        status, headers, raw = native.request_bytes(
            "GET", ITEMS + "json-id/content", audience="https://graph.microsoft.com", headers={})
        self.assertEqual(status, 302)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(raw, b"")
        self.assertIn("Location", headers)

    def test_native_permission_scan_requires_actual_reviewed_token_grant(self):
        class Credentials:
            tenant_id = TENANT
            def token(self, audience):
                return scan_token("Files.Read.All")
        class Opener:
            def open(self, request, timeout):
                raise AssertionError("Partial permission-scan credentials must fail before HTTP.")
        with self.assertRaises(GraphSyncError):
            BinaryGraphTransport(config(), Credentials(), opener=Opener()).request(
                "GET", DELTA, audience="https://graph.microsoft.com", headers={})


if __name__ == "__main__":
    unittest.main()
