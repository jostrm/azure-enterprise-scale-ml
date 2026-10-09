"""Offline tests for the opt-in Factory Chat Agent Foundry deployment."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_factory.azure import ARM, AzureError  # noqa: E402
from agent_factory import factory_chat_agent as chat  # noqa: E402

SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
GROUP = "aif-esml-project007-sdc-dev-001-rg"
GROUP_ID = f"/subscriptions/{SUB}/resourceGroups/{GROUP}"
ACCOUNT_ID = f"{GROUP_ID}/providers/Microsoft.CognitiveServices/accounts/aifacct007"
PROJECT_ID = f"{ACCOUNT_ID}/projects/aifproj007"
PROJECT_ENDPOINT = "https://aifacct007.services.ai.azure.com/api/projects/aifproj007"
MODEL = "gpt-5.4-mini"
VALUES = {
    "enableFactoryChatAgent": "true",
    "enableAIFoundry": "true",
    "deleteAllServicesForProject": "false",
    "deleteAllForProject": "false",
    "dev_test_prod_sub_id": SUB,
    "tenantId": TENANT,
    "dev_test_prod": "dev",
    "project_number_000": "007",
    "admin_aifactoryPrefixRG": "aif-",
    "projectPrefix": "esml-",
    "admin_locationSuffix": "sdc",
    "admin_aifactorySuffixRG": "-001",
    "projectSuffix": "-rg",
    "modelGPTXName": MODEL,
}


class FakeAzure:
    def __init__(self, *, agent=None, model=MODEL, endpoint=PROJECT_ENDPOINT):
        self.calls = []
        self.agent = copy.deepcopy(agent)
        self.lists = {
            f"{GROUP_ID}/resources": [
                {
                    "id": ACCOUNT_ID,
                    "name": "aifacct007",
                    "type": "Microsoft.CognitiveServices/accounts",
                    "kind": "AIServices",
                    "location": "swedencentral",
                },
            ],
            f"{ACCOUNT_ID}/projects": [
                {"id": PROJECT_ID, "name": "aifacct007/aifproj007"},
            ],
            f"{ACCOUNT_ID}/deployments": [
                {
                    "name": model,
                    "properties": {
                        "provisioningState": "Succeeded",
                        "model": {"format": "OpenAI", "name": model, "version": "2026-03-17"},
                    },
                },
            ],
        }
        self.project = {
            "id": PROJECT_ID,
            "name": "aifacct007/aifproj007",
            "properties": {"endpoints": {"AI Foundry API": endpoint}},
        }

    def pages(self, url, *, audience=ARM, field="value"):
        self.calls.append(("LIST", url, audience))
        path = url[len(ARM):].split("?", 1)[0]
        for suffix, items in self.lists.items():
            if path.endswith(suffix):
                return copy.deepcopy(items)
        return []

    def arm(self, method, resource_id, body=None, api_version="x"):
        self.calls.append((method, resource_id, api_version, copy.deepcopy(body)))
        if method == "GET" and resource_id == PROJECT_ID:
            return copy.deepcopy(self.project)
        raise AzureError(404, method, resource_id, "NotFound")

    def request(self, method, url, body=None, *, audience=ARM, headers=None):
        self.calls.append((method, url, audience, copy.deepcopy(body)))
        if method == "GET":
            if self.agent is None:
                raise AzureError(404, method, url, "NotFound")
            return copy.deepcopy(self.agent)
        if method == "POST":
            assert audience == chat.AI_AUDIENCE
            return {
                "id": f"{chat.AGENT_NAME}:2",
                "name": chat.AGENT_NAME,
                "version": "2",
                "metadata": copy.deepcopy(body["metadata"]),
            }
        raise AssertionError(f"Unexpected {method}")

    def writes(self):
        return [call for call in self.calls if call[0] in {"POST", "PUT", "PATCH", "DELETE"}]


def request(**changes):
    return chat.FactoryChatAgentRequest.from_values({**VALUES, **changes})


def existing_agent(*, owner=chat.OWNER, digest="old"):
    return {
        "name": chat.AGENT_NAME,
        "versions": {
            "latest": {
                "id": f"{chat.AGENT_NAME}:1",
                "version": "1",
                "metadata": {
                    "aifactory.managed_by": owner,
                    "aifactory.definition_hash": digest,
                },
            },
        },
    }


class RequestTests(unittest.TestCase):
    def test_values_derive_exact_project_target_and_unset_macro_is_false(self):
        parsed = request()
        self.assertEqual(GROUP, parsed.resource_group)
        self.assertEqual("007", parsed.project_number)
        self.assertEqual(MODEL, parsed.model_deployment)
        self.assertFalse(request(enableFactoryChatAgent="$(enableFactoryChatAgent)").enabled)

    def test_disabled_and_invalid_intent_never_contacts_azure(self):
        azure = FakeAzure()
        integration = chat.FactoryChatAgentIntegration(azure)
        result = integration.run(request(enableFactoryChatAgent="false"), apply=True)
        self.assertEqual("skipped", result["mode"])
        self.assertEqual([], azure.calls)

        for changes, message in (
            ({"enableAIFoundry": "false"}, "requires enableAIFoundry=true"),
            ({"deleteAllForProject": "true"}, "conflicts with deletion"),
            ({"modelGPTXName": ""}, "modelGPTXName"),
            ({"project_number_000": ""}, "project_number_000"),
            ({"enableFactoryChatAgent": "yes"}, "true or false"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                integration.run(request(**changes), apply=True)
        self.assertEqual([], azure.calls)


class DefinitionTests(unittest.TestCase):
    def test_shared_definition_contains_the_governed_chat_tools(self):
        definition = chat.agent_definition(MODEL)
        self.assertEqual({"kind", "model", "instructions", "tools"}, set(definition))
        self.assertEqual(MODEL, definition["model"])
        names = [tool["name"] for tool in definition["tools"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("knowledge_search", names)
        self.assertIn("factory_operation_status", names)
        self.assertIn("cost_monthly_project_forecast", names)
        self.assertTrue(all(tool["strict"] for tool in definition["tools"]))

    def test_runtime_foundry_deploy_uses_the_shared_definition(self):
        source = (ROOT / "40-aifactory-agent/aifactory_agent/foundry.py").read_text(encoding="utf-8")
        self.assertIn("agent_definition(settings.azure.model_deployment)", source)

    def test_shared_definition_preserves_graph_evidence_guidance(self):
        instructions = chat.agent_definition(MODEL)["instructions"]
        self.assertIn("structural [G1] and architecture [A1]", instructions)
        self.assertIn("missing or stale graph context", instructions)


class IntegrationTests(unittest.TestCase):
    def test_plan_reads_only_and_reports_the_new_version(self):
        azure = FakeAzure()
        result = chat.FactoryChatAgentIntegration(azure).run(request(), apply=False)
        self.assertEqual("plan", result["mode"])
        self.assertFalse(result["mutations"])
        self.assertEqual("create-version", result["actions"][0]["action"])
        self.assertEqual([], azure.writes())

    def test_apply_creates_the_owned_agent_version_with_exact_model(self):
        azure = FakeAzure()
        result = chat.FactoryChatAgentIntegration(azure).run(request(), apply=True)
        self.assertEqual("apply", result["mode"])
        self.assertTrue(result["mutations"])
        writes = azure.writes()
        self.assertEqual(1, len(writes))
        method, url, audience, body = writes[0]
        self.assertEqual(("POST", chat.AI_AUDIENCE), (method, audience))
        self.assertEqual(f"{PROJECT_ENDPOINT}/agents/{chat.AGENT_NAME}/versions?api-version=v1", url)
        self.assertEqual(MODEL, body["definition"]["model"])
        self.assertEqual(chat.OWNER, body["metadata"]["aifactory.managed_by"])
        self.assertEqual(chat.definition_hash(body["definition"]),
                         body["metadata"]["aifactory.definition_hash"])

    def test_matching_owned_agent_is_idempotent(self):
        digest = chat.definition_hash(chat.agent_definition(MODEL))
        azure = FakeAzure(agent=existing_agent(digest=digest))
        result = chat.FactoryChatAgentIntegration(azure).run(request(), apply=True)
        self.assertEqual("unchanged", result["status"])
        self.assertEqual([], azure.writes())

    def test_changed_owned_agent_versions_but_foreign_agent_is_refused(self):
        owned = FakeAzure(agent=existing_agent(digest="different"))
        result = chat.FactoryChatAgentIntegration(owned).run(request(), apply=True)
        self.assertEqual("updated", result["status"])
        self.assertEqual(1, len(owned.writes()))

        foreign = FakeAzure(agent=existing_agent(owner="someone-else"))
        with self.assertRaisesRegex(RuntimeError, "not owned"):
            chat.FactoryChatAgentIntegration(foreign).run(request(), apply=True)
        self.assertEqual([], foreign.writes())

    def test_missing_model_and_untrusted_endpoint_fail_before_any_write(self):
        missing = FakeAzure(model="another-model")
        with self.assertRaisesRegex(ValueError, "succeeded model deployment"):
            chat.FactoryChatAgentIntegration(missing).run(request(), apply=True)
        self.assertEqual([], missing.writes())

        endpoint = FakeAzure(endpoint="https://attacker.invalid/api/projects/stolen")
        with self.assertRaisesRegex(ValueError, "Foundry project endpoint"):
            chat.FactoryChatAgentIntegration(endpoint).run(request(), apply=True)
        self.assertEqual([], endpoint.writes())


if __name__ == "__main__":
    unittest.main()
