import tempfile
import unittest
from pathlib import Path

from sales_agent.config import ConfigurationError, Settings


def values():
    return {
        "AZURE_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        "AZURE_SUBSCRIPTION_ID": "22222222-2222-4222-8222-222222222222",
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/sales",
        "FOUNDRY_AGENT_NAME": "sales",
        "FOUNDRY_AGENT_VERSION": "1",
        "FABRIC_MCP_URL": (
            "https://api.fabric.microsoft.com/v1/mcp/workspaces/"
            "33333333-3333-4333-8333-333333333333/dataagents/"
            "44444444-4444-4444-8444-444444444444/agent"
        ),
    }


class ConfigurationTests(unittest.TestCase):
    def test_prepublication_diagnostics_do_not_need_an_agent_version_or_model(self):
        setting = Settings.from_mapping(
            {**values(), "FOUNDRY_AGENT_VERSION": ""}, allow_unpublished=True
        )
        self.assertEqual(setting.agent_version, "")

    def test_text_configuration_does_not_require_voice_or_iq(self):
        settings = Settings.from_mapping(values())
        self.assertFalse(settings.voice_enabled)
        self.assertEqual(settings.agent_version, "1")

    def test_required_fields_and_placeholders_fail(self):
        for key in values():
            for value in ("", "<replace-me>"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ConfigurationError):
                        Settings.from_mapping({**values(), key: value})

    def test_rejects_credential_forwarding_to_unapproved_endpoint(self):
        for key, url in (
            ("FOUNDRY_PROJECT_ENDPOINT", "https://example.com/api/projects/sales"),
            ("FOUNDRY_PROJECT_ENDPOINT", "http://example.services.ai.azure.com/api/projects/sales"),
            ("FOUNDRY_PROJECT_ENDPOINT", "https://u:p@example.services.ai.azure.com/api/projects/sales"),
            ("FABRIC_MCP_URL", values()["FABRIC_MCP_URL"] + "?next=https://evil.invalid"),
            ("FABRIC_MCP_URL", "https://api.fabric.microsoft.com/v1/mcp/core"),
        ):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                Settings.from_mapping({**values(), key: url})

    def test_workspace_private_host_is_bound_to_workspace(self):
        url = values()["FABRIC_MCP_URL"].replace(
            "api.fabric.microsoft.com",
            "33333333333343338333333333333333.z33.w.api.fabric.microsoft.com",
        )
        self.assertEqual(Settings.from_mapping({**values(), "FABRIC_MCP_URL": url}).fabric_url, url)
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping({**values(), "FABRIC_MCP_URL": url.replace(".z33.", ".z99.")})

    def test_voice_explicit_configuration_and_native_model_required(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping({**values(), "VOICE_ENABLED": "true"})
        setting = {
            **values(), "VOICE_ENABLED": "true",
            "VOICE_ENDPOINT": "https://voice.services.ai.azure.com",
            "VOICE_MODEL": "gpt-realtime", "VOICE_NAME": "alloy",
        }
        self.assertTrue(Settings.from_mapping(setting).voice_enabled)
        for patch in ({"VOICE_MODEL": "gpt-4.1"}, {"VOICE_API_VERSION": "invented"},
                      {"VOICE_ENABLED": "maybe"}):
            with self.assertRaises(ConfigurationError):
                Settings.from_mapping({**setting, **patch})

    def test_publication_needs_model_but_not_existing_version(self):
        settings = Settings.from_mapping(
            {**values(), "FOUNDRY_AGENT_VERSION": "", "FOUNDRY_MODEL_DEPLOYMENT": "my-deployment"},
            publication=True,
        )
        self.assertEqual(settings.model_deployment, "my-deployment")
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping({**values()}, publication=True)

    def test_domain_paths_resolve_from_env_not_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "domain.json").write_text(
                '{"instructions":"Use the supplied calendar.", "schema_mappings":{}}', encoding="utf-8"
            )
            settings = Settings.from_mapping(
                {**values(), "DOMAIN_CONFIG_PATH": "domain.json"}, base_dir=root
            )
            self.assertEqual(settings.domain_path, root / "domain.json")


if __name__ == "__main__":
    unittest.main()
