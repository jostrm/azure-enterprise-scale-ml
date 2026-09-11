from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[4]
GENERATOR = ROOT / "documentation" / "gh-io" / "tools" / "generate_parameters.py"
spec = importlib.util.spec_from_file_location("generate_parameters", GENERATOR)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class ParameterDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated, cls.counts = generator.generate()
        cls.schema = generator.load_schema()
        cls.yaml = generator.parse_template(generator.YAML, re.compile(r"^  ([\w-]+):\s*(.*)$"), cls.schema)
        cls.env = generator.parse_template(generator.GHA / ".env.template", re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$"), cls.schema)

    def test_exact_template_union_and_unique_rows(self):
        expected = {
            "yaml": set(re.findall(r"^  ([\w-]+):", generator.YAML.read_text(), re.M)),
            "env": set(re.findall(r"^([A-Z][A-Z0-9_]*)=", (generator.GHA / ".env.template").read_text(), re.M)),
        }
        document = json.loads((generator.SHARED / "variables.json").read_text())
        expected.update({f"json.{section}": set(values) for section, values in document.items()})
        for source, keys in expected.items():
            with self.subTest(source=source):
                actual = re.findall(r"<!-- parameter " + re.escape(source) + r":([^ ]+) -->", self.generated)
                self.assertEqual(keys, set(actual))
                self.assertTrue(all(count == 1 for count in Counter(actual).values()))
                self.assertEqual(len(keys), self.counts[source])

    def test_checked_in_page_is_current(self):
        page = generator.PAGE.read_text(encoding="utf-8")
        self.assertEqual(self.generated, generator.START + page.split(generator.START, 1)[1].split(generator.END, 1)[0] + generator.END)

    def test_condition_markers_do_not_become_globally_mandatory(self):
        for key, entry in [*self.yaml.items(), *self.env.items()]:
            comment = entry["comment"]
            tags = re.findall(r"<(mandatory|optional)>", comment)
            if (tags and tags[0] == "optional" and "mandatory" in tags) or "optional if" in comment.lower():
                with self.subTest(key=key):
                    self.assertEqual("C", generator.requirement(key, comment)[0])
        for key in ("TENANT_ID", "PROJECT_NUMBER"):
            self.assertEqual("M", generator.requirement(key, self.env[key]["comment"])[0])
        for key in ("ENABLE_AI_FOUNDRY", "ENABLE_FOUNDRY_CAPHOST", "ENABLE_AI_SEARCH", "ENABLE_COSMOS_DB",
                    "APIM_GATEWAY_BACKENDS_JSON", "KONG_CONSUMER_API_KEY"):
            self.assertEqual("C", generator.requirement(key, self.env[key]["comment"])[0])
        for source, key in re.findall(r"<!-- parameter ([^: ]+):([^ ]+) -->", self.generated):
            line = next(line for line in self.generated.splitlines() if f"<!-- parameter {source}:{key} -->" in line)
            cells = line.split(" | ")
            status = cells[1] if source in {"bootstrap", "helper", "state"} else cells[2]
            self.assertIn(status, {"M", "C", "O"})

    def test_real_defaults_types_and_source_duplicates(self):
        self.assertEqual("0", self.env["DEV_CIDR_RANGE"]["value"])
        self.assertEqual("64", self.env["STAGE_CIDR_RANGE"]["value"])
        self.assertEqual("128", self.env["PROD_CIDR_RANGE"]["value"])
        self.assertEqual("DataZoneStandard", self.env["MODEL_GPTX_SKU"]["value"])
        self.assertEqual("DataZoneStandard", self.env["DEFAULT_MODEL_SKU"]["value"])
        self.assertEqual("standard", self.yaml["skuAISearchStageProd"]["value"])
        self.assertEqual("acme-ai", self.env["AIFACTORY_PREFIX"]["value"])
        self.assertEqual("mrvel-1-", self.yaml["admin_aifactoryPrefixRG"]["value"])
        self.assertEqual(2, len(self.env["ADMIN_COMMON_RESOURCE_SUFFIX"]["lines"]))
        self.assertIn("Source duplicate:", self.generated)
        self.assertIn("J.dev: `false`", self.generated)

    def test_aliases_preserve_fallbacks_without_condition_collisions(self):
        mapping = generator.aliases(set(self.yaml), self.schema)
        self.assertIn("SKU_AISEARCH_STAGEPROD", mapping["skuAISearchStageProd"])
        self.assertIn("ADMIN_AISEARCH_TIER", mapping["skuAISearchStageProd"])
        self.assertIn("PROJECT_MEMBERS", mapping["technical_admins_ad_object_id"])
        self.assertNotIn("BYO_SUBNETS", mapping["subnetCommon"])
        self.assertNotIn("STAGE_CIDR_RANGE", mapping["dev_cidr_range"])
        self.assertIn("No verified", self.generated)

    def test_public_bootstrap_inputs_have_source_evidence(self):
        paths = [generator.CREATE, generator.SCHEMA,
                 ROOT / "bootstrap" / "lib" / "release_version.sh",
                 ROOT / "bootstrap" / "GH-update-aifactory-and-run-project.sh",
                 ROOT / "bootstrap" / "ADO-update-aifactory-and-run-project.sh"]
        source = "\n".join(path.read_text(encoding="utf-8-sig") for path in paths)
        for key in generator.bootstrap_inventory():
            with self.subTest(key=key):
                self.assertRegex(source, r"\b" + re.escape(key) + r"\b")
        excluded = {"AIFACTORY_LAUNCHER_STABLE", "AIF_VERSION_ARGUMENT"}
        updates = "\n".join(path.read_text() for path in paths[-2:])
        update_inputs = set(re.findall(r"\$\{((?:AIFACTORY_|ADO_|AIF_)[A-Z0-9_]+):-", updates)) - excluded
        self.assertFalse(update_inputs - set(generator.bootstrap_inventory()))
        internal_create = {
            "ADO_AGENT_NAME", "ADO_CONTEXT_SUBSCRIPTION_ID", "AIF_OIDC_CLIENT_ID", "AIF_ROUTE",
            "AIF_SIMPLE_COMMON_READY", "AIF_STATE_DIR", "AIF_TEMP_BOOTSTRAP_RG", "AIF_TEMP_MANAGED_RG",
            "AIF_VERSION_ARGUMENT",
            # Explicitly rejected by the legacy entrypoint, not accepted inputs.
            "AIF_CREATE_PROJECTS", "AIF_PROJECT_MODE",
        }
        create_inputs = set(re.findall(r"\$\{((?:AIF_|ADO_|GITHUB_)[A-Z0-9_]+):-", generator.CREATE.read_text()))
        self.assertFalse(create_inputs - internal_create - set(generator.bootstrap_inventory()))

    def test_public_bash_switches_are_documented(self):
        page = generator.PAGE.read_text(encoding="utf-8").split(generator.START, 1)[0]
        create = generator.CREATE.read_text().split("aif_scaleset_main() {", 1)[1].split("  local entry_dir", 1)[0]
        options = set(re.findall(r"^\s+(--[a-z-]+)(?:\|[^)]*)?\)", create, re.M))
        for name in ("GH-update-aifactory-and-run-project.sh", "ADO-update-aifactory-and-run-project.sh"):
            source = (ROOT / "bootstrap" / name).read_text()
            options.update(re.findall(r"^\s+(--[a-z-]+)(?:\|[^)]*)?\)", source, re.M))
        options.discard("--resume-after-bootstrap")
        for option in options:
            self.assertIn(option, page)

    def test_no_desktop_promotion_or_consumer_dependency(self):
        for name in ("advanced.md", "standard.md"):
            page = (generator.PAGE.parent / name).read_text(encoding="utf-8")
            self.assertNotRegex(page.lower(), r"maui|\.msix|\.dmg|screenshot")
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertNotIn("008_aifactory_admin", source)
        self.assertNotIn("os.environ", source)

    def test_raw_template_and_v2_project_contract_are_distinct(self):
        page = generator.PAGE.read_text(encoding="utf-8").split(generator.START, 1)[0]
        self.assertIn("not the Azure Factory v2 output schema", page)
        self.assertIn("direct top-level `dev` and `stage_prod` sections", page)
        self.assertIn("factories/<key>/scalesets/<immutable storage_suffix>/projects/projectNNN/variables.json", page)


if __name__ == "__main__":
    unittest.main()
