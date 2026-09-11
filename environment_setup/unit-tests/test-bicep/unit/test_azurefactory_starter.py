"""Offline register starter tests; fixtures stay under this repository."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[4]
BOOTSTRAP = ROOT / "bootstrap"
SPEC = importlib.util.spec_from_file_location("initialize_azurefactory", BOOTSTRAP / "lib" / "initialize_azurefactory.py")
STARTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STARTER)
BASH = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
if not BASH.is_file():
    BASH = shutil.which("bash")


def populated_document():
    factory_id = "4d989b31-95b9-4da6-aaf4-77f4c6780b12"
    return {
        "schema_version": 2, "generation": "new",
        "factories": [{
            "id": factory_id, "key": "ai-example", "kind": "ai",
            "display_name": "Example", "prefix": "example-", "region": "swedencentral",
            "status": "configured", "scale_sets": [], "projects": [],
        }],
        "configurations": {factory_id: {"factory": {}, "scale_sets": {}, "projects": {}, "variables": {}}},
        "bindings": {},
    }


class StarterWorkspace(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT / (".azurefactory-starter-test-" + uuid4().hex)
        self.workspace.mkdir()
        self.addCleanup(shutil.rmtree, self.workspace)
        self.target = self.workspace / "azurefactory"

    def snapshot(self):
        return {str(path.relative_to(self.workspace)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.workspace.rglob("*") if path.is_file()}

    def write_register(self, content):
        self.target.mkdir(exist_ok=True)
        path = self.target / "register.json"
        path.write_text(content, encoding="utf-8")
        return path


class TestAzureFactoryStarter(StarterWorkspace):
    def test_template_exactly_matches_empty_v2_contract(self):
        self.assertEqual(STARTER.read_document(STARTER.TEMPLATE), {
            "schema_version": 2, "generation": "new", "factories": [], "configurations": {}, "bindings": {},
        })
        self.assertEqual([path.name for path in STARTER.TEMPLATE.parent.iterdir()], ["register.json"])

    def test_only_register_is_created_and_rerun_preserves_bytes_and_timestamp(self):
        register, created = STARTER.initialize(self.target)
        self.assertTrue(created)
        self.assertEqual(STARTER.read_document(register), STARTER.EMPTY_DOCUMENT)
        before = self.snapshot()
        self.assertEqual(list(before), [str(Path("azurefactory") / "register.json")])
        self.assertEqual(STARTER.initialize(self.target), (register, False))
        self.assertEqual(before, self.snapshot())

    def test_empty_existing_directory_is_supported(self):
        self.target.mkdir()
        self.assertTrue(STARTER.initialize(self.target)[1])

    def test_staging_is_explicit_and_does_not_activate_a_register(self):
        templates = self.workspace / "aifactory-templates"
        templates.mkdir()
        staged = templates / "azurefactory"
        with self.assertRaises(ValueError):
            STARTER.initialize(staged)
        self.assertTrue(STARTER.initialize(staged, staging=True)[1])
        self.assertFalse(self.target.exists())
        before = self.snapshot()
        self.assertFalse(STARTER.initialize(staged, staging=True)[1])
        self.assertEqual(before, self.snapshot())
        with self.assertRaises(ValueError):
            STARTER.initialize(self.target, staging=True)

    def test_populated_staging_is_refused_without_overwrite(self):
        staged = self.workspace / "aifactory-templates" / "azurefactory"
        staged.mkdir(parents=True)
        (staged / "register.json").write_text(json.dumps(populated_document()), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "not the empty starter"):
            STARTER.initialize(staged, staging=True)
        self.assertEqual(before, self.snapshot())

    def test_populated_register_and_projections_are_never_rewritten(self):
        register = self.write_register(json.dumps(populated_document(), indent=4) + "\n")
        projection = self.target / "factories" / "ai-example" / "factory.json"
        projection.parent.mkdir(parents=True)
        projection.write_bytes(b"projection is not an editable settings template")
        before = self.snapshot()
        with patch.object(STARTER, "TEMPLATE", self.workspace / "missing-template.json"):
            self.assertEqual(STARTER.initialize(self.target), (register, False))
        self.assertEqual(before, self.snapshot())

    def test_sibling_legacy_dev_configuration_is_preserved_without_import(self):
        legacy = self.workspace / "aifactory"
        (legacy / "config-wizard").mkdir(parents=True)
        (legacy / "variables.json").write_text(
            '{"dev":{"aifactoryPrefixRG":"validspider-","aifactorySuffixRG":"-001","location":"swedencentral"}}',
            encoding="utf-8")
        (legacy / "config-wizard" / "readme.md").write_text("placeholder", encoding="utf-8")
        before = self.snapshot()
        STARTER.initialize(self.target)
        after = self.snapshot()
        for name, content in before.items():
            self.assertEqual(after[name], content)
        self.assertEqual(STARTER.read_document(self.target / "register.json")["factories"], [])

    def test_malformed_or_unsupported_registers_fail_unchanged(self):
        invalid = [
            "{", "[]", '{"schema":2}',
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, schema_version=True)),
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, schema_version=1)),
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, bindings=[])),
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, configurations={"unregistered": {}})),
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, factories=[{}])),
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, factories=populated_document()["factories"])),
            json.dumps(dict(STARTER.EMPTY_DOCUMENT, unexpected="field")),
            '{"schema_version":2,"schema_version":2,"generation":"new","factories":[],"configurations":{},"bindings":{}}',
            json.dumps(STARTER.EMPTY_DOCUMENT).replace('"new"', "NaN"),
        ]
        for content in invalid:
            with self.subTest(content=content):
                self.write_register(content)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    STARTER.initialize(self.target)
                self.assertEqual(before, self.snapshot())

    def test_wrong_named_relative_nested_and_missing_parent_roots_are_refused(self):
        (self.workspace / "aifactory").mkdir()
        (self.workspace / "aifactory-templates").mkdir()
        self.target.mkdir()
        for target in (self.workspace, Path("azurefactory"), self.workspace / "aifactory",
                       self.workspace / "absent" / "azurefactory", self.target / "azurefactory",
                       self.workspace / "aifactory" / "azurefactory",
                       self.workspace / "aifactory-templates" / "azurefactory",
                       self.workspace / ".." / "azurefactory"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                STARTER.initialize(target)
        self.assertEqual(self.snapshot(), {})

    def test_mixed_layouts_and_unregistered_nonempty_roots_are_refused(self):
        self.target.mkdir()
        for relative in ("variables.json", "config-wizard", "aifactory", "factories", "notes.txt"):
            with self.subTest(relative=relative):
                path = self.target / relative
                path.write_text("preserve", encoding="utf-8")
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    STARTER.initialize(self.target)
                self.assertEqual(before, self.snapshot())
                path.unlink()
        self.write_register(json.dumps(STARTER.EMPTY_DOCUMENT))
        (self.target / "variables.json").write_text("{}", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Mixed"):
            STARTER.initialize(self.target)
        self.assertEqual(before, self.snapshot())

    def test_invalid_template_cannot_seed_factory_metadata(self):
        template = self.workspace / "template.json"
        template.write_text(json.dumps(populated_document()), encoding="utf-8")
        with patch.object(STARTER, "TEMPLATE", template), self.assertRaisesRegex(ValueError, "exactly"):
            STARTER.initialize(self.target)
        self.assertFalse(self.target.exists())

    def test_racing_writer_wins_without_overwrite(self):
        content = json.dumps(populated_document(), indent=4)
        register = self.target / "register.json"

        def race(source, destination):
            register.write_text(content, encoding="utf-8")
            raise FileExistsError()

        with patch.object(STARTER.os, "link", side_effect=race):
            self.assertEqual(STARTER.initialize(self.target), (register, False))
        self.assertEqual(register.read_text(encoding="utf-8"), content)
        self.assertEqual(list(self.workspace.iterdir()), [self.target])

    def test_unsupported_atomic_publish_does_not_fall_back_to_overwrite(self):
        with patch.object(STARTER.os, "link", side_effect=OSError("unsupported")), self.assertRaises(OSError):
            STARTER.initialize(self.target)
        self.assertFalse((self.target / "register.json").exists())
        self.assertEqual(list(self.workspace.iterdir()), [self.target])

    def test_destination_changed_during_staging_is_not_initialized(self):
        def changed(_):
            (self.target / "user-file.json").write_text("preserve", encoding="utf-8")

        with patch.object(STARTER.os, "fsync", side_effect=changed), self.assertRaisesRegex(ValueError, "changed"):
            STARTER.initialize(self.target)
        self.assertFalse((self.target / "register.json").exists())
        self.assertEqual((self.target / "user-file.json").read_text(encoding="utf-8"), "preserve")
        self.assertEqual(list(self.workspace.iterdir()), [self.target])

    def test_hard_linked_register_is_refused(self):
        original = self.workspace / "original.json"
        original.write_text(json.dumps(STARTER.EMPTY_DOCUMENT), encoding="utf-8")
        self.target.mkdir()
        os.link(original, self.target / "register.json")
        with self.assertRaisesRegex(ValueError, "Hard-linked"):
            STARTER.initialize(self.target)

    def test_symlink_target_and_linked_register_are_refused(self):
        original = self.workspace / "original"
        original.mkdir()
        try:
            self.target.symlink_to(original, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires host privileges")
        self.addCleanup(lambda: self.target.unlink(missing_ok=True) if self.target.is_symlink() else None)
        with self.assertRaisesRegex(ValueError, "Symbolic"):
            STARTER.initialize(self.target)
        self.assertEqual(list(original.iterdir()), [])
        self.target.unlink()
        self.target.mkdir()
        linked = self.target / "register.json"
        linked.symlink_to(original / "missing.json")
        self.addCleanup(lambda: linked.unlink(missing_ok=True))
        with self.assertRaisesRegex(ValueError, "Symbolic"):
            STARTER.initialize(self.target)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_junction_target_is_refused(self):
        original = self.workspace / "original"
        original.mkdir()
        result = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J", str(self.target), str(original)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(os.rmdir, self.target)
        with self.assertRaisesRegex(ValueError, "junction"):
            STARTER.initialize(self.target)
        self.assertEqual(list(original.iterdir()), [])


@unittest.skipUnless(BASH, "Bash is unavailable")
class TestStarterBootstrapRouting(StarterWorkspace):
    def setUp(self):
        super().setUp()
        self.source = self.workspace / "azure-enterprise-scale-ml"
        for relative in ("01-aif-copy-aifactory-templates.sh", "ui/terminal.sh",
                         "lib/initialize_azurefactory.py", "templates/azurefactory/register.json"):
            destination = self.source / "bootstrap" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BOOTSTRAP / relative, destination)
        self.script = self.workspace / "01-aif-copy-aifactory-templates.sh"
        shutil.copyfile(BOOTSTRAP / self.script.name, self.script)
        self.env = dict(os.environ, AIFACTORY_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        for directory in ("aifactory-templates", "aifactory-usecase-code"):
            path = self.workspace / directory
            path.mkdir()
            (path / "keep.txt").write_text("untouched by register path", encoding="utf-8")

    def run_script(self, *args, script=None):
        return subprocess.run([str(BASH), str(script or self.script), *args],
                              cwd=self.workspace, env=self.env, input="",
                              capture_output=True, text=True, timeout=30)

    def prepare_template_sources(self):
        for relative in (
            "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines",
            "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions",
            "environment_setup/aifactory/bicep/copy_to_local_settings/automation",
            "environment_setup/aifactory/azure_dashboards", "usecase_code",
        ):
            path = self.source / relative
            path.mkdir(parents=True)
            (path / "example.txt").write_text("fixture", encoding="utf-8")
        (self.source / "bootstrap" / ".gitignore.template").write_text("fixture", encoding="utf-8")

    def test_explicit_init_and_central_script_paths_only_initialize_register(self):
        before = self.snapshot()
        result = self.run_script("--init-azurefactory")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in before.items():
            self.assertEqual(self.snapshot()[name], content)
        initialized = self.snapshot()
        result = self.run_script("--init-azurefactory", script=self.source / "bootstrap" / self.script.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(initialized, self.snapshot())

    def test_fresh_default_and_auto_copy_assets_and_stage_only_inactive_starter(self):
        self.prepare_template_sources()
        register = self.workspace / "aifactory-templates" / "azurefactory" / "register.json"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(STARTER.read_document(register), STARTER.EMPTY_DOCUMENT)
        before = (register.read_bytes(), register.stat().st_mtime_ns)
        result = self.run_script("--auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((register.read_bytes(), register.stat().st_mtime_ns), before)
        self.assertFalse(self.target.exists())
        for relative in ("aifactory-templates/esml-infra/azure-devops/bicep/yaml/example.txt",
                         "aifactory-templates/esml-infra/github-actions/bicep/example.txt",
                         "aifactory-usecase-code/example.txt"):
            self.assertTrue((self.workspace / relative).is_file())

    def test_existing_populated_register_blocks_copy_but_explicit_init_is_read_only(self):
        self.write_register(json.dumps(populated_document(), indent=4))
        before = self.snapshot()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        result = self.run_script("--init-azurefactory")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preserved existing", result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_default_copy_then_ado_02_bootstrap_retains_legacy_workflow(self):
        self.prepare_template_sources()
        pipelines = (self.source / "environment_setup" / "aifactory" / "bicep"
                     / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines")
        for directory in ("variables", "esml-infra-common", "esml-infra-project", "aifactory-governance"):
            (pipelines / directory).mkdir()
            (pipelines / directory / "fixture.txt").write_text("fixture", encoding="utf-8")
        (pipelines / "variables" / "variables.yaml").write_text("variables: {}", encoding="utf-8")
        (pipelines / "readme.md").write_text("fixture", encoding="utf-8")
        variables = {"dev": {}, "stage_prod": {}}
        (self.source / "environment_setup" / "aifactory" / "variables.json").write_text(
            json.dumps(variables), encoding="utf-8")
        script02 = self.workspace / "02-ADO-YAML-bootstrap-files.sh"
        shutil.copyfile(BOOTSTRAP / "02b-ADO-YAML-bootstrap-files.sh", script02)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_script(script=script02)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(json.loads((self.workspace / "aifactory" / "variables.json").read_text()), variables)
        self.assertTrue((self.workspace / "aifactory" / "automation" / "example.txt").is_file())

    def test_mixed_sibling_roots_require_explicit_register_only_selection(self):
        legacy = self.workspace / "aifactory"
        legacy.mkdir()
        (legacy / "variables.json").write_text('{"dev":{}}', encoding="utf-8")
        self.target.mkdir()
        before = self.snapshot()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refuses mixed/new roots", result.stderr)
        self.assertEqual(before, self.snapshot())
        result = self.run_script("--init-azurefactory")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in before.items():
            self.assertEqual(self.snapshot()[name], content)

    def test_invalid_register_and_legacy_override_fail_before_copy(self):
        self.write_register('{"schema":2}')
        before = self.snapshot()
        for args in ((), ("--legacy-templates",), ("--init-azurefactory",), ("--unsupported",)):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.snapshot())

    def test_legacy_auto_and_explicit_routes_keep_legacy_configuration(self):
        legacy = self.workspace / "aifactory"
        legacy.mkdir()
        variables = legacy / "variables.json"
        variables.write_text('{"dev":{"existing":"value"}}', encoding="utf-8")
        self.prepare_template_sources()
        for args in ((), ("--legacy-templates",)):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(variables.read_text(encoding="utf-8"), '{"dev":{"existing":"value"}}')
                self.assertFalse(self.target.exists())
                self.assertTrue((self.workspace / "aifactory-templates" / "config-wizard" / "readme.md").is_file())
                self.assertEqual((self.workspace / "aifactory-templates" / "azurefactory").exists(), not args)

    def test_populated_or_malformed_staged_register_blocks_copy_unchanged(self):
        self.prepare_template_sources()
        staged = self.workspace / "aifactory-templates" / "azurefactory"
        staged.mkdir()
        for content in ("{", json.dumps(populated_document())):
            with self.subTest(content=content):
                (staged / "register.json").write_text(content, encoding="utf-8")
                before = self.snapshot()
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.snapshot())

    def test_legacy_create_and_update_callers_select_legacy_explicitly(self):
        for relative in ("lib/create-new-aifactory-scaleset.sh",
                         "ADO-update-aifactory-and-run-project.sh", "GH-update-aifactory-and-run-project.sh"):
            source = (BOOTSTRAP / relative).read_text(encoding="utf-8")
            calls = [line for line in source.splitlines()
                     if "bash " in line and "01-aif-copy-aifactory-templates.sh" in line]
            self.assertTrue(calls)
            self.assertTrue(all("--legacy-templates" in line for line in calls))


if __name__ == "__main__":
    unittest.main()
