import copy
from dataclasses import FrozenInstanceError, replace
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request

from agent_factory.config import FactoryConfig, Target
from agent_factory.data import index_schema, json_bytes, sha256
from agent_factory import rag_sources as rag


SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"
TENANT = "11111111-1111-1111-1111-111111111111"
CONFIG = FactoryConfig(TENANT, SUBSCRIPTION, "dev", "001", "project-rg", "common-rg")
TARGET = Target(
    TENANT, SUBSCRIPTION, "project-rg", "common-rg", "foundry", "project-001",
    "https://foundry.services.ai.azure.com/api/projects/project-001", "swedencentral",
    "chat", "", "search", "aifstorage2001", "identity", "client",
)
PATH = "mlops/v1/projects/project001/environments/dev/usecases/air-passengers/rag/corpora/air-passengers/versions/v1/documents.jsonl"


def storage_id(group="common-rg", storage="commonlake"):
    return f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{group}/providers/Microsoft.Storage/storageAccounts/{storage}"


def binding():
    return {
        "location": "common", "storage_account_resource_id": storage_id(),
        "container": "lake", "blob_path": PATH, "format": "shared-lake-jsonl",
        "sha256": "a" * 64, "manifest_path": PATH.rsplit("/", 1)[0] + "/_SUCCESS.json",
        "manifest_sha256": "b" * 64, "approved_audience": "project001",
        "dataset": "air-passengers", "version": "v1", "description": "Approved teaching corpus",
        "provenance": ["https://www.kaggle.com/datasets/rakannimer/air-passengers"],
    }


def shared_document():
    text = "AirPassengers, 1949.\nPassengers were 112 thousand in January."
    return {
        "document_id": "air-passengers-1949", "text": text,
        "source_uri": "https://www.kaggle.com/datasets/rakannimer/air-passengers#year-1949",
        "source_sha256": sha256(text.encode("utf-8")), "source_version": "v1-derived-text",
        "acl": ["project001"], "deleted": False,
    }


def snapshot(rows=None, changes=None, raw=None, manifest_raw=None):
    rows = [shared_document()] if rows is None else rows
    raw = raw if raw is not None else b"\n".join(json_bytes(row) for row in rows) + b"\n"
    manifest = {
        "schema": "ml-model-factory-publication/v1", "state": "committed",
        "aifactory": "test-factory", "environment": "dev", "project": "001",
        "use_case": "air-passengers", "kind": "rag_snapshot", "format": "jsonl",
        "key": PATH.rsplit("/", 1)[0], "document_count": len(rows),
        "files": {"documents.jsonl": sha256(raw), "chunks/chunks.jsonl": "c" * 64},
        "index": {"acl_enforced": False, "deleted_document_ids": []},
        "provenance": {"master": "master/air-passengers/v1", "license": "CC0-1.0"},
    }
    manifest.update(changes or {})
    manifest_raw = manifest_raw if manifest_raw is not None else json_bytes(manifest)
    selected = binding()
    selected.update(sha256=sha256(raw), manifest_sha256=sha256(manifest_raw))
    return rag.RagSource.from_binding(selected, CONFIG, TARGET, source_key="common-air-passengers"), raw, manifest_raw


def knowledge(rows=None, raw=None):
    selected = binding()
    selected.update(
        location="project", storage_account_resource_id=storage_id("project-rg", TARGET.storage_name),
        container="agent-factory-adf", blob_path="kaggle-rag-v1/knowledge/items.json",
        format="knowledge-json-array", dataset="helpdesk", version="1",
    )
    selected.pop("manifest_path")
    selected.pop("manifest_sha256")
    row = {
        "topic": "VPN", "content": "Use the approved VPN client.",
        "source_url": "https://www.kaggle.com/datasets/dkhundley/sample-rag-knowledge-item-dataset",
        "source_version": "1", "license": "MIT", "attribution": "D. K. Hundley",
        "dataset_sha256": "d" * 64,
        "document_url": f"https://{TARGET.storage_name}.blob.core.windows.net/{selected['container']}/{selected['blob_path']}",
    }
    raw = raw if raw is not None else json_bytes([row] if rows is None else rows)
    selected["sha256"] = sha256(raw)
    return rag.RagSource.from_binding(selected, CONFIG, TARGET, source_key="project-helpdesk"), raw


class Response(io.BytesIO):
    def __init__(self, raw, url, headers=None, status=200):
        super().__init__(raw)
        self.url, self.headers, self.status = url, headers or {}, status
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class BindingTests(unittest.TestCase):
    def test_common_source_cannot_use_array_format_to_bypass_scope_acl_checks(self):
        source, _ = knowledge()
        with self.assertRaisesRegex(ValueError, "Common sources require"):
            replace(source, location="common", storage_account_resource_id=storage_id(),
                    blob_path="mlops/v1/projects/project002/environments/dev/knowledge/items.json")
    def test_common_source_does_not_change_project_target(self):
        source, _, _ = snapshot()
        self.assertEqual(source.storage_id, storage_id())
        self.assertEqual(source.storage_name, "commonlake")
        self.assertEqual(source.container, "lake")
        self.assertEqual(source.blob_path, PATH)
        self.assertEqual(source.blob_url, "https://commonlake.blob.core.windows.net/lake/" + PATH)
        self.assertEqual(TARGET.storage_name, "aifstorage2001")
        self.assertEqual(source.dataset, "air-passengers")
        self.assertEqual(source.version, "v1")

    def test_immutable_detached_binding_and_journal(self):
        original = binding()
        saved = copy.deepcopy(original)
        source = rag.RagSource.from_binding(original, CONFIG, TARGET)
        original["provenance"].append("https://example.org/other")
        original["sha256"] = "c" * 64
        journal = source.as_dict()
        journal["provenance"].append("https://example.org/mutated")
        clone = rag.RagSource.from_binding(dict(reversed(list(saved.items()))), CONFIG, TARGET)
        self.assertEqual(source.binding_fingerprint, clone.binding_fingerprint)
        self.assertNotEqual(source.binding_fingerprint, replace(source, sha256="c" * 64).binding_fingerprint)
        self.assertEqual(len(source.provenance), 1)
        with self.assertRaises(FrozenInstanceError):
            source.blob_path = "other"
        with self.assertRaisesRegex(ValueError, "project/environment"):
            replace(source, blob_path=PATH.replace("project001", "project002"))

    def test_cross_scope_accounts_and_unapproved_audiences_fail(self):
        cases = [
            {"storage_account_resource_id": storage_id().replace(SUBSCRIPTION, TENANT)},
            {"storage_account_resource_id": storage_id("project-rg")},
            {"storage_account_resource_id": storage_id(storage="lake1001")},
            {"location": "project", "storage_account_resource_id": storage_id("project-rg", "other2001")},
            {"location": "project", "storage_account_resource_id": storage_id("project-rg", "lake3001")},
            {"location": "automatic"}, {"approved_audience": "project002"},
            {"approved_audience": ["project001"]}, {"sha256": "A" * 64},
            {"sha256": ""}, {"manifest_sha256": ""},
            {"manifest_path": PATH.replace("documents.jsonl", "chunks.jsonl")},
            {"format": "pdf"}, {"dataset": "another"}, {"version": "v2"},
            {"blob_path": PATH.replace("project001", "project002")},
            {"blob_path": PATH.replace("/dev/", "/prod/")},
            {"container": "lake?sig=secret"}, {"container": "../lake"},
            {"extra": "ignored"}, {"provenance": ["https://example.org/?sig=secret"]},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rag.RagSource.from_binding({**binding(), **changes}, CONFIG, TARGET)
        for target in (replace(TARGET, subscription_id=TENANT), replace(TARGET, resource_group="other-rg")):
            with self.assertRaises(ValueError):
                rag.RagSource.from_binding(binding(), CONFIG, target)

    def test_literal_paths_only_and_no_evaluation_locations(self):
        source, _ = knowledge()
        for path in (
            "https://evil.org/knowledge/items.json", "/knowledge/items.json",
            "x\\knowledge\\items.json", "x/../knowledge/items.json",
            "x/%2e%2e/knowledge/items.json", "x/%252e%252e/knowledge/items.json",
            "x//knowledge/items.json", "x/knowledge/items.json?sig=secret",
            "x/knowledge/items.json#x", "x/raw/knowledge/items.json",
            "x/evaluation/knowledge/items.json", "x/knowledge/evaluation.json",
            "x/training/knowledge/items.json", "x/knowledge/items.pdf",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                replace(source, blob_path=path)
        self.assertEqual(replace(source, blob_path="custom-release-v1/knowledge/items.json").blob_path,
                         "custom-release-v1/knowledge/items.json")


class ParseTests(unittest.TestCase):
    def test_adf_utf8_bom_is_supported_without_changing_the_byte_hash_pin(self):
        _, raw = knowledge()
        source, bom = knowledge(raw=b"\xef\xbb\xbf" + raw)
        self.assertEqual("VPN", rag.parse_source(source, bom)[0]["topic"])
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            rag.parse_source(source, raw)
    def test_snapshot_projection_actual_manifest_and_project_wide_acl(self):
        source, raw, manifest = snapshot()
        row, = rag.parse_source(source, raw, manifest)
        expected_fields = {item["name"] for item in index_schema("rag-test")["fields"]} - {"id"}
        self.assertEqual(set(row), expected_fields)
        self.assertEqual(row["topic"], "air-passengers-1949")
        self.assertEqual(row["source_version"], "v1-derived-text")
        self.assertEqual(row["content_sha256"], shared_document()["source_sha256"])
        self.assertEqual(row["document_url"], source.blob_url)
        self.assertEqual(row["license"], "CC0-1.0")
        self.assertIsNone(row["attribution"])
        self.assertIsNone(row["dataset_sha256"])
        self.assertNotIn("acl", row)

    def test_current_knowledge_array_projection(self):
        source, raw = knowledge()
        rows = rag.parse_source(source, raw)
        self.assertEqual(rows[0]["topic"], "VPN")
        self.assertEqual(rows[0]["content_sha256"], sha256(rows[0]["content"].encode("utf-8")))
        self.assertEqual(rows[0]["license"], "MIT")

    def test_hash_pins_and_manifest_scope(self):
        source, raw, manifest = snapshot()
        for inputs in ((source, raw + b" ", manifest), (source, raw, manifest + b" "),
                       (source, raw, None)):
            with self.assertRaises(ValueError):
                rag.parse_source(*inputs)
        for changes in (
            {"state": "staged"}, {"schema": "unknown-publication/v1"},
            {"kind": "image_annotations"}, {"project": "002"}, {"environment": "prod"},
            {"use_case": "other"}, {"key": PATH.rsplit("/", 1)[0].replace("/v1", "/v2")},
            {"files": {"documents.jsonl": "e" * 64}}, {"document_count": 2},
            {"document_count": True}, {"aifactory": ""},
            {"index": {"deleted_document_ids": ["deleted-one"]}}, {"index": {}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rag.parse_source(*snapshot(changes=changes))
        with self.assertRaisesRegex(ValueError, "different AI factory"):
            rag.parse_source(replace(source, aifactory="other"), raw, manifest)

    def test_shared_acl_tombstones_unknown_fields_and_hashes(self):
        for changes in (
            {"acl": []}, {"acl": ["project001", "project002"]}, {"acl": ["user-one"]},
            {"acl": ["project002"]}, {"acl": ["project001", "project001"]},
            {"deleted": True}, {"deleted": 0}, {"deleted": None},
            {"sample_ground_truth": "EVALUATION SECRET"}, {"image": "image.jpg"},
            {"source_sha256": "f" * 64}, {"text": ""}, {"text": "a" * 60001},
            {"text": "\ud800"}, {"document_id": "bad\x00id"},
        ):
            row = {**shared_document(), **changes}
            # Escaped surrogate fixture must be serializable to exercise the parser.
            raw = json.dumps(row, ensure_ascii=True).encode("utf-8") + b"\n"
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                rag.parse_source(*snapshot(raw=raw))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rag.parse_source(*snapshot(rows=[shared_document(), shared_document()]))

    def test_no_credential_urls_or_eval_leakage_in_knowledge(self):
        _, raw = knowledge()
        row = json.loads(raw)[0]
        changes = [
            {"source_url": url} for url in (
                "http://example.org/data", "https://name:password@example.org/data",
                "https://example.org/data?sig=secret", "https://example.org/data?token=secret",
                "https://example.org/data%3Fsig=secret", "https://example.org\\@evil.org/",
                "https://example.org/\r\nsecret", "https://example.org/#token=secret",
                "https://example.org/login", "https://example.org/token/secret",
                "https://login.microsoftonline.com/common",
            )
        ]
        changes += [
            {"source_version": "2"}, {"document_url": "https://other.blob.core.windows.net/knowledge/items.json"},
            {"license": ""}, {"dataset_sha256": "bad"}, {"content_sha256": "f" * 64},
            {"sample_question": "EVALUATION SECRET"}, {"sample_ground_truth": "ANSWER"},
            {"acl": ["project001"]}, {"deleted": True},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                rag.parse_source(*knowledge(rows=[{**row, **change}]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rag.parse_source(*knowledge(rows=[row, row]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rag.parse_source(*knowledge(rows=[{**row, "id": "same"}, {**row, "id": "same", "topic": "other"}]))

    def test_malformed_duplicate_json_empty_and_oversized(self):
        for raw in (
            b"", b"\xff", b"{}", b"[]", b"[", b"<html>Sign in</html>",
            b'[{"topic":"first","topic":"second"}]', b"[NaN]", b"\x00",
            b"[" * 2000 + b"]" * 2000,
            b" " * (rag.MAX_BYTES + 1),
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                rag.parse_source(*knowledge(raw=raw))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            rag.parse_source(*snapshot(manifest_raw=b'{"kind":"rag_snapshot","kind":"other"}'))
        with self.assertRaises(ValueError):
            rag.parse_source(*snapshot(raw=b"\n"))
        with self.assertRaisesRegex(ValueError, "1000"):
            rag.parse_source(*snapshot(rows=[shared_document()] * 1001))


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.source, self.raw = knowledge()
        self.session = Mock(subscription_id=SUBSCRIPTION, tenant_id=TENANT)
        self.session.token.return_value = "operator-token"

    def read(self, response=None, **kwargs):
        response = response if response is not None else Response(self.raw, self.source.blob_url)
        with patch.object(rag, "require_private_endpoint") as private, patch.object(rag, "build_opener") as build:
            build.return_value.open.return_value = response
            result = rag.read_blob(self.session, self.source, **kwargs)
            return result, private, build

    def test_private_oauth_exact_host_no_proxy_and_bounded_get(self):
        response = Response(self.raw, self.source.blob_url)
        result, private, build = self.read(response)
        self.assertEqual(result, self.raw)
        private.assert_called_once_with(self.source.blob_url)
        self.session.token.assert_called_once_with("https://storage.azure.com/")
        handlers = build.call_args.args
        self.assertIsInstance(handlers[0], ProxyHandler)
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], rag._NoBlobRedirects)
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, self.source.blob_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer operator-token")
        self.assertEqual(request.get_header("X-ms-version"), "2023-11-03")
        self.assertTrue(all(0 < size <= 64 * 1024 for size in response.read_sizes))

    def test_arbitrary_sibling_and_wrong_sessions_fail_before_auth(self):
        for path in ("raw/items.json", self.source.blob_path + "?sig=secret", "_SUCCESS.json", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                rag.read_blob(self.session, self.source, path)
        self.session.subscription_id = TENANT
        with self.assertRaisesRegex(ValueError, "tenant and subscription"):
            rag.read_blob(self.session, self.source)
        self.session.token.assert_not_called()

    def test_manifest_read_allowed_and_pinned(self):
        source, _, manifest = snapshot()
        url = source.blob_url.rsplit("/", 1)[0] + "/_SUCCESS.json"
        with patch.object(rag, "require_private_endpoint"), patch.object(rag, "build_opener") as build:
            build.return_value.open.return_value = Response(manifest, url)
            self.assertEqual(rag.read_blob(self.session, source, source.manifest_path), manifest)

    def test_dns_failure_precedes_token_and_request(self):
        with patch.object(rag, "require_private_endpoint", side_effect=RuntimeError("No public fallback")), patch.object(rag, "build_opener") as build:
            with self.assertRaisesRegex(RuntimeError, "public fallback"):
                rag.read_blob(self.session, self.source)
            self.session.token.assert_not_called()
            build.assert_not_called()

    def test_redirects_never_forward_authorization(self):
        handler = rag._NoBlobRedirects()
        for url in ("https://evil.org/?sig=secret", self.source.blob_url):
            for code in (301, 302, 303, 307, 308):
                with self.subTest(code=code, url=url), self.assertRaisesRegex(RuntimeError, "refusing"):
                    handler.redirect_request(Request(self.source.blob_url), None, code, "Redirect", {}, url)
        with self.assertRaisesRegex(RuntimeError, "redirects"):
            self.read(Response(self.raw, "https://evil.org"))

    def test_length_actual_size_encoding_status_and_hash(self):
        cases = [
            Response(self.raw, self.source.blob_url, {"Content-Length": str(rag.MAX_BYTES + 1)}),
            Response(self.raw, self.source.blob_url, {"Content-Length": "bad"}),
            Response(self.raw, self.source.blob_url, {"Content-Length": str(len(self.raw) + 1)}),
            Response(self.raw, self.source.blob_url, {"Content-Encoding": "gzip"}),
            Response(b"x" * (rag.MAX_BYTES + 1), self.source.blob_url),
            Response(b"changed", self.source.blob_url),
            Response(self.raw, self.source.blob_url, status=206),
        ]
        for response in cases:
            with self.subTest(headers=response.headers, status=response.status), self.assertRaises((ValueError, RuntimeError)):
                self.read(response)
        for maximum in (0, -1, rag.MAX_BYTES + 1, True, 1.5):
            with self.assertRaises(ValueError):
                rag.read_blob(self.session, self.source, max_bytes=maximum)
        with self.assertRaisesRegex(ValueError, "size limit"):
            self.read(max_bytes=5)

    def test_actionable_errors_never_echo_body_signed_url_or_token(self):
        for status in (401, 403, 404, 500):
            body = io.BytesIO(b"operator-token SECRET BODY")
            error = HTTPError("https://evil.org/?sig=secret", status, "secret", {}, body)
            with patch.object(rag, "require_private_endpoint"), patch.object(rag, "build_opener") as build:
                build.return_value.open.side_effect = error
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}") as caught:
                    rag.read_blob(self.session, self.source)
            for forbidden in ("operator-token", "SECRET BODY", "sig=", "evil.org"):
                self.assertNotIn(forbidden, str(caught.exception))
            self.assertTrue(body.closed)
        with patch.object(rag, "require_private_endpoint"), patch.object(rag, "build_opener") as build:
            build.return_value.open.side_effect = URLError("https://evil.org/?sig=secret")
            with self.assertRaisesRegex(RuntimeError, "private DNS/VNet") as caught:
                rag.read_blob(self.session, self.source)
            self.assertNotIn("sig=", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
