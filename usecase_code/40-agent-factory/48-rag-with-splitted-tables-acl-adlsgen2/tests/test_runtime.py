"""Offline injected-adapter tests, not proof of deployed ACL enforcement."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from sales_demo.identity import SalesUnavailable, UserIdentity
from sales_demo.runtime import DelegatedRowStore, RowPages, SalesRuntime, config_fingerprint


GROUP = "33333333-3333-3333-3333-333333333333"
OTHER = "44444444-4444-4444-4444-444444444444"
USER = UserIdentity("11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                    frozenset({GROUP}), "search-token", "storage-token")


def row(sale_id, value=100):
    return {"dataset": "car-sales", "version": "v1", "sale_id": sale_id,
            "dealership": "North", "date": "2026-01-01", "car_model": "Car",
            "quantity": 1, "unit_price_minor": value, "discount_minor": 0,
            "refund_minor": 0, "tax_minor": 5, "status": "completed"}


def fixture():
    data = {"json": [row("a"), row("b", 200)], "excel": [row("c", 300)]}
    config = {"owner": "aif48-project001-dev", "dataset": "car-sales", "version": "v1",
              "tenant_id": USER.tenant_id, "storage_account": "samplestorage",
              "container": "lake3", "project_prefix": "projects/001/sales/v1",
              "partitions": []}
    for name, rows in data.items():
        raw = b"".join(json.dumps(value, sort_keys=True).encode() + b"\n" for value in rows)
        config["partitions"].append({
            "id": name, "input_path": f"ingestion/{name}/sales.json",
            "rows_path": f"structured/{name}/rows.jsonl", "input_sha256": "a" * 64,
            "rows_sha256": hashlib.sha256(raw).hexdigest(), "row_count": len(rows),
            "sale_ids_sha256": hashlib.sha256(("\n".join(sorted(r["sale_id"] for r in rows)) + "\n").encode()).hexdigest(),
            "expected_chunks": 3, "allowed_group_ids": [GROUP], "allowed_user_ids": [],
        })
    return config, data


class Auth:
    def __init__(self, identity=USER):
        self.identity = identity
        self.calls = 0

    def authorize(self):
        self.calls += 1
        return self.identity


class Store:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.error = None

    def open_rows(self, partition, identity):
        self.calls.append(("rows", partition["id"]))
        if self.error:
            raise self.error
        return RowPages(self.data[partition["id"]])

    def read_input(self, partition, identity):
        self.calls.append(("input", partition["id"]))
        return {"url": "https://samplestorage.blob.core.windows.net/lake3/approved",
                "sha256": partition["input_sha256"], "etag": '"source-v1"'}


class Search:
    def __init__(self):
        self.calls = []
        self.error = None

    def verify_partition(self, partition, identity):
        self.calls.append(partition["id"])
        if self.error:
            raise self.error
        return {"index": "idx-" + partition["id"], "verified": True,
                "chunk_count": partition["expected_chunks"],
                "input_sha256": partition["input_sha256"], "ingestion_succeeded": True,
                "accessed_indexes": ["idx-" + partition["id"], "audit-" + partition["id"]]}

    def retrieve(self, question, partitions, identity):
        return [{"text": "untrusted evidence", "partition": p["id"],
                 "index": "idx-" + p["id"]} for p in partitions]


def runtime(config=None, data=None):
    defaults, default_data = fixture()
    config, data = config or defaults, data or default_data
    ready = {"state": "verified", "owner": config["owner"], "dataset": config["dataset"],
             "version": config["version"], "config_sha256": config_fingerprint(config)}
    return SalesRuntime(config, ready, Auth(), Store(data), Search(), page_size=1)


class RuntimeTests(unittest.TestCase):
    def test_dirty_graph_scope_blocks_before_any_source_or_auth_reads(self):
        service = runtime()
        with patch("sales_demo.runtime.guard_snapshot", side_effect=SalesUnavailable()):
            for operation in (service.aggregate_sales, lambda: service.retrieve_sales("evidence")):
                with self.assertRaises(SalesUnavailable):
                    operation()
        self.assertEqual(service.authorization.calls, 0)
        self.assertEqual(service.store.calls, [])
        self.assertEqual(service.search.calls, [])

    def test_permission_notification_during_a_tool_discards_the_result(self):
        service = runtime()
        with patch("sales_demo.runtime.assert_guard_unchanged", side_effect=SalesUnavailable()):
            with self.assertRaises(SalesUnavailable):
                service.aggregate_sales()
            with self.assertRaises(SalesUnavailable):
                service.retrieve_sales("evidence")
        self.assertEqual(service.trace, [])

    def test_one_call_exhausts_multiple_partitions_and_pages(self):
        service = runtime()
        result = service.aggregate_sales("all")
        self.assertEqual(result["total_minor"], 600)
        self.assertEqual(service.search.calls, ["json", "excel"])
        self.assertEqual(service.authorization.calls, 1)
        self.assertEqual({p["partition"] for p in result["provenance"]}, {"json", "excel"})
        self.assertEqual(service.trace[0]["indexes"], ["idx-json", "idx-excel"])
        self.assertEqual(service.trace[0]["accessed_indexes"],
                         ["idx-json", "audit-json", "idx-excel", "audit-excel"])

    def test_restricted_all_exposes_only_allowed_partition(self):
        config, data = fixture()
        config["partitions"][1]["allowed_group_ids"] = [OTHER]
        service = runtime(config, data)
        result = service.aggregate_sales("all")
        self.assertEqual(result["total_minor"], 300)
        self.assertEqual(service.search.calls, ["json"])
        self.assertNotIn("excel", json.dumps(result))
        with self.assertRaisesRegex(SalesUnavailable, "^Sales data unavailable\\.$"):
            service.aggregate_sales("excel")
        self.assertEqual(service.search.calls, ["json"])

    def test_unauthorized_partition_need_not_exist(self):
        config, data = fixture()
        config["partitions"][1]["allowed_group_ids"] = [OTHER]
        del data["excel"]
        self.assertEqual(runtime(config, data).aggregate_sales()["total_minor"], 300)

    def test_publication_gate_fails_before_source_reads(self):
        for change in [{"state": "generated"}, {"version": "v2"}, {"config_sha256": "bad"}]:
            service = runtime()
            service.readiness.update(change)
            with self.assertRaises(SalesUnavailable):
                service.aggregate_sales()
            self.assertFalse(service.store.calls)
            self.assertFalse(service.search.calls)

    def test_fatal_denied_missing_chunk_or_missing_source_is_not_partial(self):
        for component in ("search", "store"):
            service = runtime()
            getattr(service, component).error = PermissionError("hidden resource name")
            with self.assertRaisesRegex(SalesUnavailable, "^Sales data unavailable\\.$"):
                service.aggregate_sales()
            self.assertFalse(service.trace)
        service = runtime()
        service.search.verify_partition = lambda p, i: {
            "index": "idx", "verified": True, "chunk_count": 2, "input_sha256": p["input_sha256"]}
        with self.assertRaises(SalesUnavailable):
            service.aggregate_sales()

    def test_row_version_missing_rows_and_duplicate_conflict_fail(self):
        for mutation in (
            lambda data: data["excel"].clear(),
            lambda data: data["excel"][0].update(version="v2"),
            lambda data: data["excel"][0].update(sale_id="a"),
        ):
            config, data = fixture()
            mutation(data)
            with self.assertRaises(SalesUnavailable):
                runtime(config, data).aggregate_sales()

    def test_identical_cross_source_overlap_is_counted_once(self):
        config, data = fixture()
        data["excel"] = [deepcopy(data["json"][0])]
        config["partitions"][1]["sale_ids_sha256"] = hashlib.sha256(b"a\n").hexdigest()
        service = runtime(config, data)
        result = service.aggregate_sales()
        self.assertEqual(result["total_minor"], 300)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(sum(result["source_subtotals_minor"].values()), 300)

    def test_conflicting_cross_source_payload_is_fatal_after_valid_coverage(self):
        config, data = fixture()
        data["excel"][0]["sale_id"] = "a"
        config["partitions"][1]["sale_ids_sha256"] = hashlib.sha256(b"a\n").hexdigest()
        service = runtime(config, data)
        with self.assertRaises(SalesUnavailable):
            service.aggregate_sales()
        self.assertFalse(service.trace)

    def test_missing_authorized_partition_is_not_a_zero_subtotal(self):
        config, data = fixture()
        del data["excel"]
        service = runtime(config, data)
        with self.assertRaises(SalesUnavailable):
            service.aggregate_sales()
        self.assertFalse(service.trace)

    def test_retrieval_discloses_only_authorized_citations(self):
        config, data = fixture()
        config["partitions"][1]["allowed_group_ids"] = [OTHER]
        service = runtime(config, data)
        result = service.retrieve_sales("Show relevant sales evidence")
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["evidence"][0]["partition"], "json")
        self.assertNotIn("excel", json.dumps(result))
        self.assertEqual(service.store.calls, [("input", "json")])

    def test_retrieval_rechecks_returned_content_against_verified_chunk_hashes(self):
        service = runtime()
        original = service.search.verify_partition

        def verified(partition, identity):
            return {**original(partition, identity),
                    "chunk_hashes": {"known": hashlib.sha256(b"verified").hexdigest()}}

        service.search.verify_partition = verified
        service.search.retrieve = lambda question, partitions, identity: [
            {"partition": "json", "index": "idx-json", "text": "changed", "chunk_id": "known"}]
        with self.assertRaises(SalesUnavailable):
            service.retrieve_sales("evidence")
        self.assertFalse(service.trace)

    def test_pagination_cycles_and_empty_intermediate_pages_fail(self):
        for rows in ([row("a")], []):
            service = runtime()
            class Broken:
                def page(self, cursor, limit):
                    return {"rows": rows, "next": "same"}
            service.store.open_rows = lambda p, i: Broken()
            with self.assertRaises(SalesUnavailable):
                service.aggregate_sales()

    def test_no_scoped_policy_means_no_data(self):
        service = runtime()
        service.authorization.identity = UserIdentity(USER.tenant_id, USER.oid, frozenset(), "s", "b")
        with self.assertRaises(SalesUnavailable):
            service.aggregate_sales()
        self.assertFalse(service.search.calls)

    def test_row_store_rejects_hash_corruption_and_unapproved_paths(self):
        config, _ = fixture()
        store = DelegatedRowStore(config)
        with patch.object(store, "_read", return_value=(b'{"bad":"row"}\n', '"v1"')):
            with self.assertRaises(SalesUnavailable):
                store.open_rows(config["partitions"][0], USER)
        altered = deepcopy(config["partitions"][0])
        altered["rows_path"] = "../evaluation/expected.json"
        with self.assertRaises(SalesUnavailable):
            store.open_rows(altered, USER)

    def test_storage_uses_user_token_if_match_and_no_redirect_or_proxy(self):
        config, _ = fixture()
        store = DelegatedRowStore(config)
        requests = []

        class Response:
            def __init__(self):
                self.headers = {"ETag": '"v1"', "Content-Length": "4"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b"data"

        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Response()

        with patch("sales_demo.runtime.build_opener", return_value=Opener()) as build, patch(
            "agent_factory.data.require_private_endpoint"
        ) as private:
            raw, etag = store._read(store.root + config["partitions"][0]["input_path"], USER)
            private.assert_called_once()
        self.assertEqual(raw, b"data")
        self.assertEqual(requests[0].get_method(), "HEAD")
        self.assertEqual(requests[1].get_header("If-match"), '"v1"')
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer storage-token")
        self.assertEqual(build.call_args.args[0].proxies, {})
        with self.assertRaises(SalesUnavailable):
            build.call_args.args[1].redirect_request(None, None, 302, "", None, "https://evil.example")

    def test_native_denial_probe_distinguishes_forbidden_from_missing_or_broad_access(self):
        config, _ = fixture()
        store = DelegatedRowStore(config)
        for status in (403, 404, 500):
            with patch("sales_demo.runtime.build_opener") as build:
                build.return_value.open.side_effect = HTTPError("private", status, "", {}, None)
                self.assertEqual(store.verify_native_denial(USER, allowed_partition="json"), status == 403)
        with patch("sales_demo.runtime.build_opener"):
            self.assertFalse(store.verify_native_denial(USER, allowed_partition="json"))


if __name__ == "__main__":
    unittest.main()
