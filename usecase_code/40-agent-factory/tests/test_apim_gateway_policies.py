"""Offline contracts for the classic APIM AI gateway policy package and MCP exposure.

These mirror the native AI Gateway SKU features (client IP and user throttling, semantic
caching, token metrics, MCP tool servers) on a classic or v2 API Management service. No Azure
deployment or authentication: source checks plus an optional local Bicep build.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "environment_setup" / "aifactory" / "bicep").is_dir():
    ROOT = ROOT / "azure-enterprise-scale-ml"
APIM = ROOT / "environment_setup" / "aifactory" / "bicep" / "esml-common" / "ai-gateway" / "apim"
CONFIGURATION = APIM / "apim-configuration.bicep"
ENTRY = APIM / "main.bicep"
POLICY = APIM / "policy.xml"
FRAGMENTS = APIM / "apim-policy-fragments.bicep"
MCP = APIM / "apim-mcp-server.bicep"
README = APIM / "README.md"
IP_KEY = "@(context.Request.IpAddress)"
USER_KEY = 'context.Variables.GetValueOrDefault<Jwt>("entra-token")'


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def resources(template: dict) -> list[dict]:
    value = template["resources"]
    return list(value.values()) if isinstance(value, dict) else value


class PolicyTemplateTests(unittest.TestCase):
    def test_existing_limits_stay_and_optional_slots_are_ordered(self):
        policy = text(POLICY)
        for existing in ('counter-key="azure-openai-gpt55-pool-global"', 'counter-key="@(context.Subscription.Id)"',
                         '<authentication-managed-identity resource="https://cognitiveservices.azure.com" />'):
            self.assertIn(existing, policy)
        slots = ("__ENTRA_VALIDATION__", "__CLIENT_LIMITS__", "__USER_LIMITS__", "__TOKEN_METRICS__",
                 "__SEMANTIC_CACHE_LOOKUP__", "__SEMANTIC_CACHE_STORE__")
        positions = [policy.index(slot) for slot in slots]
        # Callers are validated before they are counted; the cache is read after backend auth is set.
        self.assertLess(positions[0], policy.index("pool-global"))
        self.assertLess(policy.index("authentication-managed-identity"), positions[4])
        self.assertLess(policy.index("<outbound>"), positions[5])
        self.assertLess(positions[1], positions[2])


class ParameterContractTests(unittest.TestCase):
    def test_new_features_are_opt_in_and_keep_the_deployed_policy(self):
        configuration = text(CONFIGURATION)
        for declaration in (
            "param clientIpTokensPerMinute int = 0", "param clientIpRequestsPerMinute int = 0",
            "param userTokensPerMinute int = 0", "param entraTenantId string = ''",
            "param entraClientApplicationIds array = []", "param entraAudiences array = []",
            "param emitTokenMetrics bool = false", "param applicationInsightsLoggerName string = ''",
            "param enableSemanticCache bool = false", "param semanticCacheScoreThreshold string = '0.05'",
            "param semanticCacheDurationSeconds int = 120", "param embeddingsBackendUrl string = ''",
            "param semanticCacheConnectionString string = ''",
        ):
            self.assertIn(declaration, configuration)
        self.assertRegex(configuration, r"@secure\(\)\s*(?:@description\([^)]*\)\s*)?param semanticCacheConnectionString")

    def test_entry_passes_every_policy_parameter_and_optional_mcp_servers(self):
        entry = text(ENTRY)
        for name in ("clientIpTokensPerMinute", "clientIpRequestsPerMinute", "userTokensPerMinute",
                     "entraTenantId", "entraClientApplicationIds", "entraAudiences", "emitTokenMetrics",
                     "applicationInsightsLoggerName", "enableSemanticCache", "semanticCacheScoreThreshold",
                     "semanticCacheDurationSeconds", "embeddingsBackendUrl", "semanticCacheConnectionString"):
            self.assertRegex(entry, rf"(?m)^\s*{name}: {name}$")
        self.assertIn("param mcpServers array = []", entry)
        self.assertIn("module apimMcpServers 'apim-mcp-server.bicep' = [for", entry)


class FragmentTests(unittest.TestCase):
    def test_fragments_are_shared_once_by_both_apis(self):
        for path in (CONFIGURATION, MCP):
            self.assertRegex(text(path), r"import \{[^}]+\} from 'apim-policy-fragments\.bicep'")
        fragments = text(FRAGMENTS)
        for function in ("entraValidationXml", "clientLimitsXml", "userLimitsXml", "tokenMetricsXml",
                         "semanticCacheLookupXml", "semanticCacheStoreXml"):
            self.assertRegex(fragments, rf"@export\(\)\s*(?:@description\('[^']*'\)\s*)?func {function}\(")

    def test_client_ip_throttling_counts_tokens_and_requests_per_ip(self):
        fragments = text(FRAGMENTS)
        self.assertIn(f'<rate-limit-by-key calls="${{requestsPerMinute}}" renewal-period="60" counter-key="{IP_KEY}"',
                      fragments)
        self.assertIn(f'<llm-token-limit counter-key="{IP_KEY}" tokens-per-minute="${{tokensPerMinute}}"', fragments)

    def test_user_throttling_uses_only_validated_entra_claims(self):
        fragments = text(FRAGMENTS)
        self.assertIn('output-token-variable-name="entra-token"', fragments)
        self.assertIn("<validate-azure-ad-token", fragments)
        self.assertIn(USER_KEY, fragments)
        self.assertIn('GetValueOrDefault("oid"', fragments)
        # Unvalidated tokens can be forged to dodge per-user limits.
        self.assertNotIn("AsJwt()", fragments)
        self.assertNotIn("x-user-id", fragments)

    def test_unsafe_combinations_fail_at_compile_time(self):
        fragments = text(FRAGMENTS)
        for message in ("userTokensPerMinute requires entraTenantId",
                        "entraTenantId requires entraClientApplicationIds or entraAudiences",
                        "enableSemanticCache requires embeddingsBackendUrl and semanticCacheConnectionString",
                        "emitTokenMetrics requires applicationInsightsLoggerName"):
            self.assertIn(message, fragments)
        self.assertGreaterEqual(fragments.count("fail("), 4)

    def test_semantic_cache_never_shares_answers_across_callers(self):
        fragments = text(FRAGMENTS)
        self.assertIn("<llm-semantic-cache-lookup", fragments)
        self.assertIn('embeddings-backend-auth="system-assigned"', fragments)
        self.assertIn("<vary-by>@(context.Subscription.Id)</vary-by>", fragments)
        self.assertIn('ignore-system-messages="true"', fragments)
        self.assertIn("<llm-semantic-cache-store duration=", fragments)


class McpServerModuleTests(unittest.TestCase):
    def test_module_passes_an_existing_streamable_mcp_through_apim(self):
        module = text(MCP)
        self.assertIn("targetScope = 'resourceGroup'", module)
        # A plain HTTP reverse proxy of the streamable endpoint, so the backend MCP answers every call.
        for fragment in ("Microsoft.ApiManagement/service/apis@2025-09-01-preview", "type: 'http'",
                         "serviceUrl: requireHttpsBaseUrl(mcpServerBaseUrl)", "urlTemplate: mcpEndpointPath",
                         "param mcpEndpointPath string = '/mcp'", "param subscriptionRequired bool = true",
                         "param clientIpRequestsPerMinute int = 60", "func requireHttpsBaseUrl(",
                         "authentication-managed-identity resource=", '<forward-request buffer-response="false" />'):
            self.assertIn(fragment, module)
        # type 'mcp' with mcpProperties made APIM answer as its own tool-less MCP server (2026-10-19).
        self.assertNotIn("type: 'mcp'", module)
        self.assertNotIn("mcpProperties", module)
        # Reading the response body buffers the stream and breaks MCP streaming.
        self.assertNotIn("context.Response.Body", module)
        self.assertIn("output gatewayMcpUrl string", module)

    def test_module_can_issue_one_client_subscription_scoped_to_the_mcp_api(self):
        module = text(MCP)
        self.assertIn("param clientSubscriptionName string = ''", module)
        self.assertIn("if (!empty(clientSubscriptionName))", module)
        self.assertIn("scope: '/apis/${mcpApi.name}'", module)
        self.assertIn("output clientSubscriptionResourceId string", module)

    def test_readme_documents_parity_and_prerequisites(self):
        readme = text(README)
        for topic in ("Client IP throttling", "User throttling", "Semantic cache", "Token metrics",
                      "MCP servers", "AiFactory.Mcp.Read"):
            self.assertIn(topic, readme)


class CompiledTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        az, bicep = shutil.which("az"), shutil.which("bicep")
        if az:
            cls.command = [az, "bicep", "build"]
        elif bicep:
            cls.command = [bicep, "build"]
        else:
            raise unittest.SkipTest("Existing Azure CLI/Bicep CLI required for compiled contracts")
        cls.templates = {path.name: cls.build(path) for path in (CONFIGURATION, MCP, ENTRY)}

    @classmethod
    def build(cls, path: Path) -> dict:
        result = subprocess.run(cls.command + ["--file", str(path), "--stdout"], capture_output=True, text=True,
                                encoding="utf-8", timeout=180, check=False)
        if result.returncode:
            raise AssertionError(f"Bicep compilation failed for {path.name}:\n{result.stderr}")
        if re.search(r"\b(?:Warning|Error) (?:BCP\d+|[a-z-]+):", result.stderr):
            raise AssertionError(f"Bicep diagnostics must be resolved for {path.name}:\n{result.stderr}")
        return json.loads(result.stdout)

    def test_mcp_api_is_an_unbuffered_streamable_http_passthrough(self):
        template = self.templates[MCP.name]
        of_type = lambda kind: [item for item in resources(template) if item["type"] == kind]  # noqa: E731
        apis = of_type("Microsoft.ApiManagement/service/apis")
        self.assertEqual(1, len(apis))
        # Older api-versions cannot see a type 'mcp' API (GET/PUT say "Api not found", DELETE is a no-op);
        # this version converts an existing one in place (verified on apim-spider-sdc-dev-001, 2026-10-19).
        self.assertEqual("2025-09-01-preview", apis[0]["apiVersion"])
        self.assertEqual("http", apis[0]["properties"]["type"])
        self.assertNotIn("mcpProperties", apis[0]["properties"])
        # Streamable HTTP: POST carries JSON-RPC, GET opens the server stream, DELETE ends a session.
        operations = of_type("Microsoft.ApiManagement/service/apis/operations")
        self.assertEqual(1, len(operations))
        self.assertIn("copy", operations[0])
        self.assertEqual(["POST", "GET", "DELETE"], template["variables"]["mcpMethods"])
        self.assertEqual(1, len(of_type("Microsoft.ApiManagement/service/apis/policies")))
        self.assertIn('<backend><forward-request buffer-response="false" /></backend>',
                      json.dumps(template["variables"]["policyXml"]).replace('\\"', '"'))
        # Optional: the AI gateway pipeline issues one client subscription; Spider keeps its own.
        subscriptions = of_type("Microsoft.ApiManagement/service/subscriptions")
        self.assertEqual(1, len(subscriptions))
        self.assertIn("clientSubscriptionName", subscriptions[0]["condition"])
        self.assertEqual("", template["parameters"]["clientSubscriptionName"]["defaultValue"])

    def test_compiled_policy_carries_ip_and_cache_fragments(self):
        compiled = json.dumps(self.templates[CONFIGURATION.name])
        self.assertIn(IP_KEY, compiled)
        self.assertIn("llm-semantic-cache-lookup", compiled)
        caches = [item for item in resources(self.templates[CONFIGURATION.name])
                  if item["type"] == "Microsoft.ApiManagement/service/caches"]
        self.assertEqual(1, len(caches))
        self.assertIn("enableSemanticCache", caches[0]["condition"])


if __name__ == "__main__":
    unittest.main()
