import copy
import unittest

from sales_demo.images import ImageClient, build_image_definitions, verify_image_evidence


def configuration():
    root = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/"
    return {
        "owner": "aif48-project001-dev", "version": "v1",
        "search_endpoint": "https://demo.search.windows.net",
        "source_storage_resource_id": root + "syntheticimages",
        "asset_storage_resource_id": root + "syntheticassets",
        "protected_storage_resource_ids": [root + "saleslake", root + "masterlake"],
        "source_container": "synthetic-images", "asset_container": "synthetic-assets",
        "source_prefix": "synthetic/images/v1/", "synthetic_only": True,
        "ai_services_endpoint": "https://models.services.ai.azure.com",
        "model_endpoint": "https://models.services.ai.azure.com",
        "chat_deployment": "gpt-4o", "chat_model": "gpt-4o",
        "embedding_deployment": "text-embedding-3-large",
        "input_kind": "png-derivative",
    }


class Transport:
    def __init__(self, response):
        self.calls = []
        self.response = response
        self.resources = {}

    def request(self, method, url, body=None, *, audience, headers=None):
        self.calls.append((method, url, body, audience, headers))
        if method == "GET":
            return copy.deepcopy(self.resources[url])
        return copy.deepcopy(self.response)


class ImageTests(unittest.TestCase):
    def test_exact_isolated_schema(self):
        plan = build_image_definitions(configuration())
        ks = plan["resources"]["knowledge_source"]
        kb = plan["resources"]["knowledge_base"]
        self.assertEqual(ks["kind"], "azureBlob")
        params = ks["azureBlobParameters"]
        self.assertEqual(params["folderPath"], "synthetic/images/v1/")
        ingestion = params["ingestionParameters"]
        self.assertEqual(ingestion["contentExtractionMode"], "standard")
        self.assertNotIn("ingestionPermissionOptions", ingestion)
        self.assertEqual(ingestion["assetStore"]["containerName"], "synthetic-assets")
        self.assertEqual(ingestion["aiServices"], {"uri": "https://models.services.ai.azure.com"})
        self.assertEqual(kb["models"], [ingestion["chatCompletionModel"]])
        self.assertTrue(kb["knowledgeSources"][0]["enableImageServing"])
        self.assertEqual(kb["outputMode"], "answerSynthesis")

    def test_never_reuses_sales_storage_or_permissions(self):
        for field, value in (
            ("source_storage_resource_id", configuration()["protected_storage_resource_ids"][0]),
            ("asset_storage_resource_id", configuration()["protected_storage_resource_ids"][1]),
            ("source_prefix", "ingestion/json/sales/"),
            ("synthetic_only", False),
            ("ingestionPermissionOptions", ["userIds"]),
        ):
            config = configuration()
            config[field] = value
            with self.assertRaises(ValueError):
                build_image_definitions(config)

    def test_retrieve_requires_explicit_execution_and_real_activity(self):
        response = {"activity": [{"type": "azureBlob", "imageServing": {"imagesSentToModel": 2}}],
                    "servedImages": [{"id": "actual"}], "response": [{"content": [{"text": "Answer"}]}]}
        transport = Transport(response)
        client = ImageClient(configuration(), transport)
        plan = client.plan()
        response["activity"][0]["knowledgeSourceName"] = plan["names"]["knowledge_source"]
        for kind, collection in (("knowledge_source", "knowledgesources"), ("knowledge_base", "knowledgebases")):
            resource = plan["resources"][kind]
            transport.resources[client._url(f"{collection}/{resource['name']}")] = resource
        self.assertEqual(transport.calls, [])
        with self.assertRaises(ValueError):
            client.retrieve("diagram")
        evidence = client.retrieve("diagram", execute=True)
        self.assertEqual(evidence["images_sent_to_model"], 2)
        self.assertEqual(evidence["servedImages"], response["servedImages"])
        self.assertFalse(evidence["docx_pass"])
        body = transport.calls[-1][2]
        self.assertTrue(body["includeActivity"])
        self.assertEqual(body["knowledgeSourceParams"][0]["kind"], "azureBlob")
        self.assertTrue(body["knowledgeSourceParams"][0]["enableImageServing"])
        self.assertEqual(body["outputMode"], "answerSynthesis")

    def test_retrieve_refuses_modified_source_before_model_call(self):
        transport = Transport({})
        client = ImageClient(configuration(), transport)
        for kind, collection in (("knowledge_source", "knowledgesources"), ("knowledge_base", "knowledgebases")):
            resource = client.plan()["resources"][kind]
            transport.resources[client._url(f"{collection}/{resource['name']}")] = resource
        source_url = next(url for url in transport.resources if "/knowledgesources/" in url)
        transport.resources[source_url]["azureBlobParameters"]["folderPath"] = "protected/sales/"
        with self.assertRaises(ValueError):
            client.retrieve("diagram", execute=True)
        self.assertFalse(any(call[0] == "POST" for call in transport.calls))

    def test_answer_or_verbalization_is_not_image_evidence(self):
        for response in (
            {"response": "I saw the image"},
            {"servedImages": [{"id": "x"}]},
            {"activity": [{"imageServing": {"imagesRetrieved": 1, "imagesSentToModel": 0, "verbalizationUsed": True}}]},
            {"activity": [{"imageServing": {"imagesSentToModel": True}}]},
        ):
            with self.assertRaises(ValueError):
                verify_image_evidence(response, input_kind="png-derivative")

    def test_a_declared_docx_format_is_not_direct_extraction_evidence(self):
        result = verify_image_evidence(
            {"activity": [{"imageServing": {"imagesSentToModel": 1}}]}, input_kind="docx",
        )
        self.assertTrue(result["image_serving_verified"])
        self.assertFalse(result["docx_pass"])


if __name__ == "__main__":
    unittest.main()
