import copy
import csv
from dataclasses import replace
from email.message import Message
import io
import json
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from agent_factory.azure import AzureError, AzureSession
from agent_factory.config import Target
from agent_factory import data


def target():
    return Target(
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id="22222222-2222-2222-2222-222222222222",
        resource_group="project-rg", common_resource_group="common-rg",
        account_name="foundry-account", project_name="project-001",
        project_endpoint="https://foundry-account.services.ai.azure.com/api/projects/project-001",
        location="swedencentral", model_deployment="chat", embedding_deployment="",
        search_name="project-search", storage_name="aifstorage2001",
        identity_id="/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/project-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/project-mi",
        identity_client_id="33333333-3333-3333-3333-333333333333",
    )


def csv_bytes(rows=None):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(data.CSV_COLUMNS)
    writer.writerows(rows if rows is not None else [
        ("VPN", "# VPN guide\n\nUse the approved client, then sign in.", "How to connect?", "EVALUATION SECRET ONE"),
        ("VPN", "# VPN guide\n\nUse the approved client, then sign in.", "Can I use VPN?", "EVALUATION SECRET TWO"),
    ])
    return buffer.getvalue().encode("utf-8")


class MemorySearch:
    def __init__(self):
        self.index = None
        self.documents = {}
        self.calls = []
        self.fail_upload = False

    def request(self, method, url, body=None, **kwargs):
        self.calls.append((method, url, copy.deepcopy(body), kwargs))
        if "/docs/search?" in url:
            if body.get("queryType") == "semantic":
                return {"value": [{"id": next(iter(self.documents)), "@search.rerankerScore": 2.8}]}
            return {"@odata.count": len(self.documents), "value": list(self.documents.values())[body.get("skip", 0):][:1000]}
        if "/docs/index?" in url:
            if not self.fail_upload:
                self.documents.update({doc["id"]: {key: value for key, value in doc.items() if key != "@search.action"}
                                       for doc in body["value"]})
            return {"value": [{"key": doc["id"], "status": not self.fail_upload,
                               "statusCode": 503 if self.fail_upload else 201} for doc in body["value"]]}
        if method == "GET":
            if self.index is None:
                raise AzureError(404, method, url, "missing")
            return copy.deepcopy(self.index)
        if method == "PUT":
            self.index = copy.deepcopy(body)
            return self.index
        raise AssertionError((method, url, body))


class DatasetTests(unittest.TestCase):
    def test_multiline_deduplicated_and_evaluation_separated(self):
        parsed = data.parse_dataset(csv_bytes())
        self.assertEqual((parsed.row_count, len(parsed.documents), len(parsed.evaluations)), (2, 1, 2))
        self.assertIn("\n\n", parsed.documents[0]["content"])
        indexed = json.dumps(parsed.documents)
        self.assertNotIn("EVALUATION SECRET", indexed)
        self.assertNotIn("sample_question", indexed)
        self.assertNotIn("sample_ground_truth", indexed)
        self.assertEqual(parsed.documents[0]["id"], parsed.evaluations[0]["document_id"])
        self.assertEqual(parsed.raw_sha256, data.sha256(csv_bytes()))

    def test_ids_stable_across_row_order_and_newlines(self):
        rows = [("VPN", "Line1\r\nLine2", "Q", "A"), ("VPN", "Different content", "Q2", "A2")]
        first = data.parse_dataset(csv_bytes(rows))
        second = data.parse_dataset(csv_bytes(list(reversed(rows))))
        self.assertEqual([doc["id"] for doc in first.documents], [doc["id"] for doc in second.documents])
        normalized = data.parse_dataset(csv_bytes([("VPN", "Line1\nLine2", "new question", "new answer")]))
        self.assertIn(normalized.documents[0]["id"], [doc["id"] for doc in first.documents])

    def test_same_content_different_topic_is_distinct(self):
        parsed = data.parse_dataset(csv_bytes([("One", "Shared", "Q", "A"), ("Two", "Shared", "Q", "A")]))
        self.assertEqual(len(parsed.documents), 2)

    def test_invalid_csv_is_rejected(self):
        invalid = [
            b"", b"<html>Sign in</html>", b"\xff",
            b"ki_topic,ki_text,sample_question,sample_ground_truth,extra\nA,B,C,D,E",
            b"ki_topic,ki_text,sample_question,sample_ground_truth\nA,B,C",
            b"ki_topic,ki_text,sample_question,sample_ground_truth\nA,B,C,D,E",
            b'ki_topic,ki_text,sample_question,sample_ground_truth\nA,"unterminated,C,D',
            b"ki_topic,ki_text,sample_question,sample_ground_truth\nA,\x00B,C,D",
            csv_bytes([]), csv_bytes([("A", "", "Q", "A")]),
        ]
        for raw in invalid:
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                data.parse_dataset(raw)

    def test_size_and_row_limits(self):
        with patch.object(data, "MAX_DOWNLOAD_BYTES", 5), self.assertRaisesRegex(ValueError, "size"):
            data.parse_dataset(csv_bytes())
        with patch.object(data, "MAX_ROWS", 1), self.assertRaisesRegex(ValueError, "row limit"):
            data.parse_dataset(csv_bytes())

    def test_storage_target_2001_only(self):
        data.validate_target(target())
        for storage in ("aifstorage1001", "aifstorage10012001", "aifstorage3001"):
            with self.subTest(storage=storage), self.assertRaisesRegex(ValueError, "2001"):
                data.validate_target(replace(target(), storage_name=storage))

    def test_cross_project_identity_refused(self):
        with self.assertRaisesRegex(ValueError, "project resource group"):
            data.validate_target(replace(target(), identity_id=target().identity_id.replace("project-rg", "other-rg")))

    def test_private_dns_no_public_or_loopback_fallback(self):
        for address, valid in (("10.0.0.4", True), ("172.16.2.3", True),
                               ("20.10.5.5", False), ("127.0.0.1", False)):
            with self.subTest(address=address), patch.object(socket, "getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),
            ]):
                if valid:
                    data.require_private_endpoint(target().search_endpoint)
                else:
                    with self.assertRaisesRegex(RuntimeError, "private VNet"):
                        data.require_private_endpoint(target().search_endpoint)

    def test_schema_rejects_eval_or_unowned_index(self):
        schema = data.index_schema("aif-test")
        data.validate_index(schema, "aif-test")
        for changed in (
            {**schema, "description": "another owner"},
            {**schema, "fields": schema["fields"] + [{"name": "sample_ground_truth"}]},
            {**schema, "semantic": {}},
        ):
            with self.assertRaises(ValueError):
                data.validate_index(changed, "aif-test")


class DownloadTests(unittest.TestCase):
    def response(self, raw, content_type="text/csv", length=None):
        response = MagicMock()
        response.__enter__.return_value = response
        headers = Message()
        headers["Content-Type"] = content_type
        if length is not None:
            headers["Content-Length"] = str(length)
        response.headers = headers
        response.read.return_value = raw
        return response

    def test_bounded_anonymous_canonical_download(self):
        response = self.response(csv_bytes())
        with patch.object(data, "build_opener") as opener:
            opener.return_value.open.return_value = response
            self.assertEqual(data.download_dataset(), csv_bytes())
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, data.DOWNLOAD_URL)
        self.assertNotIn("Authorization", request.headers)
        response.read.assert_called_once_with(data.MAX_DOWNLOAD_BYTES + 1)

    def test_bad_content_type_html_and_size(self):
        for response in (
            self.response(b"<html>login</html>", "text/html"),
            self.response(b"<html>login</html>", "text/plain"),
            self.response(b"zip", "application/zip"),
            self.response(b"a", length=data.MAX_DOWNLOAD_BYTES + 1),
        ):
            with patch.object(data, "build_opener") as opener, self.assertRaises(ValueError):
                opener.return_value.open.return_value = response
                data.download_dataset()

    def test_download_errors_never_log_signed_url(self):
        with patch.object(data, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://storage.googleapis.com/file?secret=SIGNATURE", 403, "", {}, None)
            with self.assertRaisesRegex(RuntimeError, "HTTP 403") as raised:
                data.download_dataset()
        self.assertNotIn("SIGNATURE", str(raised.exception))

    def test_redirect_refuses_http_and_unknown_host(self):
        handler = data._HttpsDatasetRedirects()
        for url in ("http://storage.googleapis.com/file", "https://example.org/file"):
            with self.assertRaises(RuntimeError):
                handler.redirect_request(None, None, 302, "", {}, url)


class IngestionTests(unittest.TestCase):
    def test_mi_explicit_client_id_and_no_cli(self):
        identity = MagicMock()
        with patch.dict(sys.modules, {"azure.identity": SimpleNamespace(ManagedIdentityCredential=identity)}):
            self.assertIs(data._managed_identity(target().identity_client_id), identity.return_value)
            identity.assert_called_once_with(client_id=target().identity_client_id)
        credential = MagicMock()
        credential.get_token.return_value.token = "mi-token"
        with patch.object(AzureSession, "token", side_effect=AssertionError("CLI forbidden")):
            session = data._ManagedIdentitySession(target(), credential)
            self.assertEqual(session.token(data.SEARCH_AUDIENCE), "mi-token")
            credential.get_token.assert_called_once_with("https://search.azure.com/.default")
            with self.assertRaises(ValueError):
                session.token("https://management.azure.com")

    def test_missing_mi_stops_before_download(self):
        credential = MagicMock()
        credential.get_token.side_effect = RuntimeError("UAMI is not attached")
        with patch.object(data, "require_private_endpoint"), patch.object(data, "_managed_identity", return_value=credential), \
                patch.object(data, "download_dataset") as download:
            with self.assertRaisesRegex(RuntimeError, "UAMI is not attached"):
                data.ingest(target())
            download.assert_not_called()
        credential.close.assert_called_once()

    def run_ingest(self, search):
        artifacts = {}
        credential = MagicMock()
        service = MagicMock()
        def put_blob(container, name, raw, content_type, metadata):
            artifacts[name] = raw
        with patch.object(data, "require_private_endpoint"), patch.object(data, "_managed_identity", return_value=credential), \
                patch.object(data, "_ManagedIdentitySession", return_value=search), \
                patch.object(data, "download_dataset", return_value=csv_bytes()), \
                patch.object(data, "_blob_service", return_value=service), \
                patch.object(data, "_private_container"), patch.object(data, "_put_blob", side_effect=put_blob):
            result = data.ingest(target())
        return result, artifacts, credential, service

    def test_ingestion_persists_separate_artifacts_and_idempotent_index(self):
        search = MemorySearch()
        result, artifacts, credential, service = self.run_ingest(search)
        self.assertEqual(result["document_count"], 1)
        self.assertEqual(result["evaluation_count"], 2)
        self.assertFalse(result["embeddings_required"])
        self.assertEqual(len(artifacts), 4)
        self.assertEqual(artifacts[f"kaggle-rag-v1/raw/{data.DATASET_FILE}"], csv_bytes())
        self.assertIn(b"EVALUATION SECRET", artifacts["kaggle-rag-v1/evaluation/samples.jsonl"])
        self.assertNotIn("EVALUATION SECRET", json.dumps(search.calls))
        manifest = json.loads(artifacts["kaggle-rag-v1/manifest.json"])
        self.assertEqual(manifest["source_url"], data.DATASET_URL)
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["raw_sha256"], data.sha256(csv_bytes()))
        credential.close.assert_called_once()
        service.close.assert_called_once()
        self.run_ingest(search)
        self.assertEqual(sum(method == "PUT" for method, *_ in search.calls), 1)
        self.assertEqual(len(search.documents), 1)

    def test_partial_search_upload_failure_is_not_success(self):
        search = MemorySearch()
        search.fail_upload = True
        with self.assertRaisesRegex(RuntimeError, "503"):
            self.run_ingest(search)

    def test_unrelated_existing_documents_refused(self):
        search = MemorySearch()
        search.index = data.index_schema("aif-kaggle-rag-v1")
        search.documents = {"other": {"id": "other", "dataset_sha256": "unknown", "content_sha256": "unknown"}}
        with self.assertRaisesRegex(ValueError, "another dataset"):
            self.run_ingest(search)
        self.assertFalse(any("/docs/index?" in url for _, url, *_ in search.calls))

    def test_unauthorized_index_read_is_not_treated_as_missing(self):
        search = MagicMock()
        search.request.side_effect = AzureError(403, "GET", target().search_endpoint, "forbidden")
        with self.assertRaises(AzureError) as raised:
            self.run_ingest(search)
        self.assertEqual(raised.exception.status, 403)
        search.request.assert_called_once()

    def test_blob_existing_collision_and_private_container(self):
        class ResourceExistsError(Exception):
            pass
        container = MagicMock()
        blob = container.get_blob_client.return_value
        blob.upload_blob.side_effect = ResourceExistsError("exists")
        blob.get_blob_properties.return_value.size = 999
        with patch.dict(sys.modules, {
            "azure.core.exceptions": SimpleNamespace(ResourceExistsError=ResourceExistsError),
            "azure.storage.blob": SimpleNamespace(ContentSettings=MagicMock()),
        }):
            with self.assertRaisesRegex(ValueError, "identical"):
                data._put_blob(container, "raw/data.csv", b"abc", "text/csv", {})
            blob.get_blob_properties.return_value.size = 3
            blob.get_blob_properties.return_value.metadata = {"owner": data.OWNER, "sha256": data.sha256(b"abc")}
            blob.download_blob.return_value.readall.return_value = b"abc"
            data._put_blob(container, "raw/data.csv", b"abc", "text/csv", {})
            blob.download_blob.return_value.readall.return_value = b"xyz"
            with self.assertRaisesRegex(ValueError, "content differs"):
                data._put_blob(container, "raw/data.csv", b"abc", "text/csv", {})
            service = MagicMock()
            service.get_container_client.return_value.get_container_properties.return_value = {"public_access": "blob"}
            with self.assertRaisesRegex(ValueError, "public access"):
                data._private_container(service, "agent-factory")

    def test_new_blob_persistence_is_verified(self):
        class ResourceExistsError(Exception):
            pass
        container = MagicMock()
        blob = container.get_blob_client.return_value
        blob.get_blob_properties.return_value.size = 0
        with patch.dict(sys.modules, {
            "azure.core.exceptions": SimpleNamespace(ResourceExistsError=ResourceExistsError),
            "azure.storage.blob": SimpleNamespace(ContentSettings=MagicMock()),
        }):
            with self.assertRaisesRegex(RuntimeError, "persistence verification"):
                data._put_blob(container, "raw/data.csv", b"abc", "text/csv", {})
        self.assertFalse(blob.upload_blob.call_args.kwargs["overwrite"])


if __name__ == "__main__":
    unittest.main()
