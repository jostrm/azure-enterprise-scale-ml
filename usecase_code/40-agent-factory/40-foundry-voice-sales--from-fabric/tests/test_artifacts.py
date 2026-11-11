import ast
import json
import re
import unittest
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


class ArtifactTests(unittest.TestCase):
    def test_scoped_line_endings_keep_git_copies_identical_on_windows(self):
        self.assertIn("* text=auto eol=lf", (ROOT / ".gitattributes").read_text(encoding="utf-8"))

    def test_notebook_is_unexecuted_compilable_and_contains_no_embedded_outputs(self):
        notebook = json.loads((ROOT / "quickstart.ipynb").read_text(encoding="utf-8"))
        self.assertEqual(notebook["nbformat"], 4)
        self.assertTrue(notebook["cells"])
        for cell in notebook["cells"]:
            self.assertNotIn("attachments", cell)
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                ast.parse("".join(cell["source"]))

    def test_primary_manifest_is_satisfied_by_reproducible_lock(self):
        pins = {}
        for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            requirement = Requirement(line)
            self.assertRegex(str(requirement.specifier), r"^==[^*,]+$")
            pins[requirement.name.lower().replace("_", "-")] = requirement
            self.assertIn(version(requirement.name), requirement.specifier)
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            requirement = Requirement(line)
            pin = pins[requirement.name.lower().replace("_", "-")]
            self.assertIn(version(pin.name), requirement.specifier)

    def test_new_python_sources_compile_without_importing_or_contacting_services(self):
        for folder in ("sales_agent", "scripts", "tests"):
            for path in (ROOT / folder).rglob("*.py"):
                with self.subTest(path=path.relative_to(ROOT)):
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_no_known_credential_literal_or_excluded_backend_import(self):
        secret = re.compile(
            r"""(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\s*=\s*["'][A-Za-z0-9_+/=-]{24,}["']"""
        )
        forbidden_imports = {"aifactory" + "_agent", "agent" + "_factory"}
        for path in (ROOT / "sales_agent").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(secret.search(text), path)
            for node in ast.walk(ast.parse(text)):
                modules = ([node.module] if isinstance(node, ast.ImportFrom)
                           else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                self.assertFalse(any(module and module.split(".")[0] in forbidden_imports for module in modules),
                                 path)

    def test_env_example_has_placeholders_not_customer_identity_or_credentials(self):
        from dotenv import dotenv_values

        values = dotenv_values(ROOT / ".env.example", interpolate=False)
        for key in ("AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"):
            self.assertRegex(values[key], r"^<.*>$")
        for key in ("AZURE_EXPECTED_USER", "AZURE_RESOURCE_GROUP", "TEAM_GROUP_ID"):
            self.assertFalse(values[key])
        self.assertEqual(values["VOICE_ENABLED"], "false")
        self.assertFalse(any("SECRET" in key or "TOKEN" in key or "PASSWORD" in key for key in values))


if __name__ == "__main__":
    unittest.main()
