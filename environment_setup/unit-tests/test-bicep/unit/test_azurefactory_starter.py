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
                         "lib/initialize_azurefactory.py", "lib/bootstrap_no_delete.py",
                         "templates/azurefactory/register.json"):
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
        for relative in ("environment_setup/azurefactory-cli",
                         "environment_setup/install_config_wizard/api-usage-examples"):
            shutil.copytree(ROOT / relative, self.source / relative,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv",
                                                        "*.egg-info", "build", "dist", ".local"))

    def run_no_delete(self, *args, script=None):
        audit = self.workspace / "audit"
        audit.mkdir(exist_ok=True)
        if not (audit / "sitecustomize.py").exists():
            (audit / "sitecustomize.py").write_text(
                "import sys\n"
                "def no_removal(event, args):\n"
                "    if event in {'os.remove', 'os.rmdir', 'shutil.rmtree'}:\n"
                "        raise RuntimeError('FORBIDDEN_REMOVAL: ' + event)\n"
                "sys.addaudithook(no_removal)\n", encoding="utf-8")
        command = (
            'rm() { echo FORBIDDEN_RM >&2; return 99; }; '
            'rmdir() { echo FORBIDDEN_RMDIR >&2; return 99; }; '
            'gh() { echo FORBIDDEN_CLOUD >&2; return 99; }; '
            'az() { echo FORBIDDEN_CLOUD >&2; return 99; }; '
            'export -f rm rmdir gh az; bash "$@"'
        )
        return subprocess.run(
            [str(BASH), "--noprofile", "--norc", "-c", command, "no-delete-test",
             str(script or self.script), "--no-delete", *args],
            cwd=self.workspace, env=dict(self.env, PYTHONPATH=str(audit)), input="",
            capture_output=True, text=True, timeout=60)

    def prepare_start_bundle(self):
        shutil.copytree(BOOTSTRAP, self.source / "bootstrap", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        script = self.source / "00-start.sh"
        shutil.copyfile(ROOT / script.name, script)
        return script

    def test_no_delete_start_backs_up_dirty_bundle_and_installs_both_helpers(self):
        script = self.prepare_start_bundle()
        dirty = {
            "ADO-azurefactory.sh": b"my changed launcher\n",
            "lib/layout_router.sh": b"my changed router\n",
            "ui/terminal.sh": b"my changed terminal\n",
            "01-aif-copy-aifactory-templates.sh": b"my changed copier\n",
        }
        preserved = {
            ".github/workflows/infra-common.yml": b"my workflow",
            ".gitignore": b"private-config.json\n",
            "aifactory/variables.json": b'{"dev":{"existing":"configuration"}}',
        }
        for relative, content in {**dirty, **preserved}.items():
            path = self.workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        result = self.run_no_delete(script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("FORBIDDEN_", result.stdout + result.stderr)
        self.assertNotIn("Choose your orchestrator", result.stdout)
        self.assertIn("--init-azurefactory", result.stdout)
        backups = list((self.workspace / ".aifactory-backups").iterdir())
        self.assertEqual(len(backups), 1)
        for relative, content in dirty.items():
            self.assertEqual((backups[0] / relative).read_bytes(), content)
            self.assertEqual((self.workspace / relative).read_bytes(), (BOOTSTRAP / relative).read_bytes())
        for relative, content in preserved.items():
            self.assertEqual((self.workspace / relative).read_bytes(), content)
        for relative in ("02-ADO-YAML-bootstrap-files.sh", "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh",
                         "02-GH-bootstrap-files.sh", "03-GH-bootstrap-files-no-env-overwrite.sh",
                         "lib/bootstrap_no_delete.py", "lib/initialize_azurefactory.py",
                         "lib/factory_lifecycle_contract.txt", "templates/azurefactory/register.json"):
            self.assertTrue((self.workspace / relative).is_file(), relative)
        self.assertFalse(self.target.exists())
        result = self.run_no_delete(script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list((self.workspace / ".aifactory-backups").iterdir()), backups)

    def test_no_delete_start_checks_complete_bundle_before_overwriting(self):
        script = self.prepare_start_bundle()
        missing = self.source / "bootstrap/GHA-azurefactory.sh"
        missing.rename(missing.with_suffix(".missing"))
        before = self.snapshot()
        result = self.run_no_delete(script=script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Complete dual-layout launcher bundle", result.stderr)
        for relative, value in before.items():
            self.assertEqual(self.snapshot()[relative], value)
        self.assertFalse((self.workspace / "ADO-azurefactory.sh").exists())
        self.assertFalse((self.workspace / ".aifactory-backups").exists())

    def test_no_delete_start_at_registered_root_refreshes_only_control_bundle(self):
        script = self.prepare_start_bundle()
        self.write_register(json.dumps(populated_document(), indent=4))
        before = self.snapshot()
        result = self.run_no_delete(script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Template copy remains blocked", result.stdout)
        for relative in ("azurefactory/register.json", "aifactory-templates/keep.txt",
                         "aifactory-usecase-code/keep.txt"):
            self.assertEqual(self.snapshot()[str(Path(relative))], before[str(Path(relative))])

    def test_no_delete_refresh_preserves_sentinels_and_versions_for_all_modes(self):
        self.prepare_template_sources()
        templates = self.workspace / "aifactory-templates"
        preserved = {
            ".gitignore": b"my private ignore rules",
            "aifactory/variables.json": b'{"dev":{"existing":"value"}}',
            "aifactory-templates/keep.txt": b"template sentinel",
            "aifactory-usecase-code/keep.txt": b"usecase sentinel",
            "aifactory-templates/config-wizard/readme.md": b"my wizard notes",
            "aifactory-templates/azurefactory-cli/.gitignore": b"my CLI ignore rules",
        }
        changed = (
            "aifactory-templates/esml-infra/azure-devops/bicep/yaml/example.txt",
            "aifactory-usecase-code/example.txt",
            "aifactory-templates/azurefactory-cli/src/azurefactory/cli.py",
            "aifactory-templates/install_config_wizard/api-usage-examples/python/inspect_factory.py",
        )
        for relative, content in preserved.items():
            path = self.workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        previous_backups = set()
        staged = templates / "azurefactory/register.json"
        for mode in ((), ("--auto",), ("--legacy-templates",)):
            with self.subTest(mode=mode):
                for relative in changed:
                    path = self.workspace / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"my modified version")
                register_before = (staged.read_bytes(), staged.stat().st_mtime_ns) if staged.exists() else None
                result = self.run_no_delete(*mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("FORBIDDEN_", result.stdout + result.stderr)
                backups = set((self.workspace / ".aifactory-backups").iterdir())
                self.assertEqual(len(backups - previous_backups), 1)
                backup = (backups - previous_backups).pop()
                previous_backups = backups
                for relative in changed:
                    self.assertEqual((backup / relative).read_bytes(), b"my modified version")
                    self.assertNotEqual((self.workspace / relative).read_bytes(), b"my modified version")
                for relative, content in preserved.items():
                    self.assertEqual((self.workspace / relative).read_bytes(), content)
                self.assertFalse(self.target.exists())
                self.assertEqual(STARTER.read_document(staged), STARTER.EMPTY_DOCUMENT)
                if register_before:
                    self.assertEqual((staged.read_bytes(), staged.stat().st_mtime_ns), register_before)
        result = self.run_script("--init-azurefactory")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(STARTER.read_document(self.target / "register.json"), STARTER.EMPTY_DOCUMENT)
        for relative, content in preserved.items():
            self.assertEqual((self.workspace / relative).read_bytes(), content)

    def test_no_delete_direct_and_installed_copiers_ship_api_without_runtime_artifacts(self):
        script = self.prepare_start_bundle()
        self.prepare_template_sources()
        result = self.run_no_delete(script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        source_cli = self.source / "environment_setup/azurefactory-cli"
        for relative in ("src/azurefactory/saved.receipt.json", "tests/.local/private.json",
                         "src/azurefactory/__pycache__/cached.py"):
            path = source_cli / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not distributable", encoding="utf-8")
        for copier in (self.source / "bootstrap" / self.script.name, self.script):
            result = self.run_no_delete("--legacy-templates", script=copier)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.workspace / "aifactory-templates/azurefactory").exists())
        cli = self.workspace / "aifactory-templates/azurefactory-cli"
        self.assertTrue((cli / "src/azurefactory/cli.py").is_file())
        self.assertFalse((cli / "src/azurefactory/saved.receipt.json").exists())
        self.assertFalse((cli / "tests/.local").exists())
        self.assertFalse((cli / "src/azurefactory/__pycache__").exists())

    def test_no_delete_refuses_unsafe_layout_and_type_conflicts_without_overwrite(self):
        self.prepare_template_sources()
        conflict = self.workspace / "aifactory-templates/esml-infra"
        conflict.write_text("existing file, not a directory", encoding="utf-8")
        before = self.snapshot()
        result = self.run_no_delete()
        self.assertNotEqual(result.returncode, 0)
        for relative, value in before.items():
            self.assertEqual(self.snapshot()[relative], value)
        self.assertFalse((self.workspace / ".aifactory-backups").exists())
        self.target.mkdir()
        for mode in ((), ("--auto",), ("--legacy-templates",)):
            result = self.run_no_delete(*mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refuses mixed/new roots", result.stderr)

    def test_no_delete_preserves_nonempty_staged_register_on_failure(self):
        self.prepare_template_sources()
        register = self.workspace / "aifactory-templates/azurefactory/register.json"
        register.parent.mkdir()
        for document in ("{", json.dumps(populated_document())):
            register.write_text(document, encoding="utf-8")
            before = self.snapshot()
            result = self.run_no_delete()
            self.assertNotEqual(result.returncode, 0)
            for relative, value in before.items():
                self.assertEqual(self.snapshot()[relative], value)
            self.assertFalse((self.workspace / ".aifactory-backups").exists())

    def test_no_delete_refuses_linked_destination_without_changing_its_target(self):
        self.prepare_template_sources()
        original = self.workspace / "original.txt"
        original.write_bytes(b"preserve linked user file")
        destination = self.workspace / "aifactory-usecase-code/example.txt"
        os.link(original, destination)
        before = self.snapshot()
        result = self.run_no_delete()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Hard-linked", result.stderr)
        for relative, value in before.items():
            self.assertEqual(self.snapshot()[relative], value)
        self.assertFalse((self.workspace / ".aifactory-backups").exists())

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

    def test_cli_and_api_sources_are_copied_for_each_template_mode(self):
        self.prepare_template_sources()
        for args in ((), ("--auto",), ("--legacy-templates",)):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                templates = self.workspace / "aifactory-templates"
                for relative in (
                    "azurefactory-cli/.gitignore", "azurefactory-cli/readme.md",
                    "azurefactory-cli/pyproject.toml", "azurefactory-cli/src/azurefactory/cli.py",
                    "azurefactory-cli/src/azurefactory/review.py", "azurefactory-cli/tests/test_reviews.py",
                    "install_config_wizard/api-usage-examples/.gitignore",
                    "install_config_wizard/api-usage-examples/readme.md",
                    "install_config_wizard/api-usage-examples/python/inspect_factory.py",
                    "install_config_wizard/api-usage-examples/powershell/Request-AzureFactory.ps1",
                    "install_config_wizard/api-usage-examples/node/request.mjs",
                    "install_config_wizard/api-usage-examples/requests/01-create-factory.json",
                    "install_config_wizard/api-usage-examples/scenarios.json",
                ):
                    copied = templates / relative
                    source = self.source / "environment_setup" / relative
                    self.assertEqual(copied.read_bytes(), source.read_bytes(), relative)
                examples = templates / "install_config_wizard" / "api-usage-examples"
                self.assertTrue((examples / "../../azurefactory-cli/readme.md").is_file())
                self.assertTrue((templates / "azurefactory-cli/../install_config_wizard/api-usage-examples/readme.md").is_file())
                for copied in (templates / "azurefactory-cli", examples):
                    self.assertFalse((copied / ".venv").exists())
                self.assertIn("CLI, Python SDK and API usage examples", result.stdout)

    def test_cli_api_copy_excludes_runtime_artifacts_and_refreshes_stale_files(self):
        self.prepare_template_sources()
        cli = self.source / "environment_setup" / "azurefactory-cli"
        examples = self.source / "environment_setup" / "install_config_wizard" / "api-usage-examples"
        excluded = [
            cli / ".venv" / "sensitive.py",
            cli / "src" / "azurefactory" / "__pycache__" / "cached.py",
            cli / "tests" / ".local" / "private.json",
            cli / "src" / "azurefactory" / "saved.receipt.json",
            examples / ".local" / "bootstrap.json",
            examples / "requests" / "saved.review.json",
            examples / "requests" / "saved.private.json",
            examples / "node" / "node_modules" / "dependency.mjs",
            examples / "python" / ".env",
        ]
        for path in excluded:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("do-not-copy", encoding="utf-8")
        (cli / "operator-config.json").write_text("not a distributable root asset", encoding="utf-8")
        result = self.run_script("--legacy-templates")
        self.assertEqual(result.returncode, 0, result.stderr)
        templates = self.workspace / "aifactory-templates"
        for path in excluded:
            relative = path.relative_to(self.source / "environment_setup")
            self.assertFalse((templates / relative).exists(), relative)
        self.assertFalse((templates / "azurefactory-cli/operator-config.json").exists())
        stale = templates / "azurefactory-cli/src/azurefactory/removed.py"
        stale.write_text("stale template", encoding="utf-8")
        result = self.run_script("--legacy-templates")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stale.exists())

    def test_missing_cli_api_source_fails_before_replacing_templates(self):
        self.prepare_template_sources()
        (self.source / "environment_setup" / "azurefactory-cli" / "pyproject.toml").unlink()
        before = self.snapshot()
        result = self.run_script("--legacy-templates")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLI/API source is missing", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_failed_cli_api_archive_is_reported_without_success_banner(self):
        self.prepare_template_sources()
        result = subprocess.run(
            [str(BASH), "--noprofile", "--norc", "-c",
             'tar() { return 73; }; export -f tar; bash "$AIF_TEST_COPY_SCRIPT" --legacy-templates'],
            cwd=self.workspace, env=dict(self.env, AIF_TEST_COPY_SCRIPT=self.script.as_posix()),
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLI/API template copy failed", result.stderr)
        self.assertNotIn("Template copy finished", result.stdout)

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
