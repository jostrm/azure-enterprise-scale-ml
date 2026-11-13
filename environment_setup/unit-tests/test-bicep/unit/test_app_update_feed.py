"""Offline contract tests for the four desktop applications' shared release feed."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import warnings


ROOT = Path(__file__).resolve().parents[4]
SETUP = ROOT / "environment_setup"
SPEC = importlib.util.spec_from_file_location("app_update_feed", SETUP / "generate_app_updates.py")
FEED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FEED)


class AppUpdateFeedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def package(self, folder, name, content=b"installer"):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        sums = path.parent / "SHA256SUMS.txt"
        with sums.open("a", encoding="utf-8") as stream:
            stream.write(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
        return path

    def test_unpublished_apps_remain_explicitly_unavailable(self):
        document = FEED.build_feed(self.root)
        self.assertEqual(1, document["schemaVersion"])
        self.assertEqual(
            {"aifactory-config", "esaif-configwizard", "esaif-configwizard-project", "esaif-tutorialapp"},
            set(document["apps"]),
        )
        self.assertTrue(all(not app["platforms"] for app in document["apps"].values()))

    def test_nonexistent_source_is_not_reported_as_empty_releases(self):
        with self.assertRaisesRegex(ValueError, "source directory"):
            FEED.build_feed(self.root / "missing")

    def test_numeric_newest_msi_includes_all_matching_cab_files(self):
        folder = "install_config_wizard/maui"
        for version in ("1.0.9", "1.0.10"):
            self.package(folder, f"ESAIF.ConfigWizard-{version}-win-x64.msi")
            for number in (1, 2):
                self.package(folder, f"ESAIF.ConfigWizard-{version}-win-x64-{number}.cab")
        document = FEED.build_feed(self.root)
        release = document["apps"]["esaif-configwizard"]["platforms"]["windows-x64"]
        self.assertEqual("1.0.10", release["version"])
        self.assertEqual("msi", release["installerType"])
        self.assertEqual(3, len(release["files"]))
        self.assertTrue(release["files"][0]["path"].endswith(".msi"))
        self.assertTrue(all("1.0.10" in item["path"] for item in release["files"]))
        self.assertEqual({}, document["apps"]["esaif-configwizard-project"]["platforms"])

    def test_project_uses_its_own_installer_identity(self):
        folder = "install_config_wizard_project/maui"
        self.package(folder, "ESAIF.ConfigWizardProject-1.0.4-win-x64-setup.exe")
        self.package(folder, "ESAIF.ConfigWizardProject-1.0.4-win-x64-setup-1.bin")
        release = FEED.build_feed(self.root)["apps"]["esaif-configwizard-project"]["platforms"]["windows-x64"]
        self.assertEqual("1.0.4", release["version"])
        self.assertIn("ESAIF.ConfigWizardProject-", release["files"][0]["path"])
        self.assertEqual("inno", release["installerType"])
        self.assertEqual("{D77386A2-9B9B-4A66-B493-A8E5B57EBB7B}", release["innoAppId"])
        self.assertEqual(2, len(release["files"]))

    def test_project_never_substitutes_configwizard_msi(self):
        folder = "install_config_wizard_project/maui"
        self.package(folder, "ESAIF.ConfigWizard-1.0.4-win-x64.msi")
        self.package(folder, "ESAIF.ConfigWizard-1.0.4-win-x64-1.cab")
        self.assertEqual({}, FEED.build_feed(self.root)["apps"]["esaif-configwizard-project"]["platforms"])

    def test_missing_project_bin_cannot_be_published(self):
        folder = "install_config_wizard_project/maui"
        self.package(folder, "ESAIF.ConfigWizardProject-1.0.4-win-x64-setup.exe")
        self.package(folder, "ESAIF.ConfigWizardProject-1.0.4-win-x64-setup-1.bin").unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            FEED.build_feed(self.root)

    def test_tutorial_supports_existing_preview_filename(self):
        folder = "install_tutorial_guide"
        stem = "ESAF-Tutorials-0.2.3-win-x64-local-preview-unsigned"
        self.package(folder, f"{stem}.msi")
        self.package(folder, f"{stem}-1.cab")
        release = FEED.build_feed(self.root)["apps"]["esaif-tutorialapp"]["platforms"]["windows-x64"]
        self.assertEqual("0.2.3", release["version"])
        self.assertEqual(2, len(release["files"]))

    def test_missing_declared_cab_cannot_be_published(self):
        folder = "install_config_wizard/maui"
        self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64.msi")
        cab = self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64-1.cab")
        cab.unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            FEED.build_feed(self.root)

    def test_missing_checksum_inventory_is_not_a_complete_release(self):
        folder = "install_config_wizard/maui"
        msi = self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64.msi")
        (msi.parent / "SHA256SUMS.txt").unlink()
        with self.assertRaisesRegex(ValueError, "SHA256SUMS"):
            FEED.build_feed(self.root)

    def test_cab_not_in_inventory_is_not_silently_omitted(self):
        folder = "install_config_wizard/maui"
        msi = self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64.msi")
        self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64-1.cab")
        (msi.parent / "ESAIF.ConfigWizard-1.0.1-win-x64-2.cab").write_bytes(b"cab")
        with self.assertRaisesRegex(ValueError, "inventory"):
            FEED.build_feed(self.root)

    def test_unsafe_inventory_path_is_rejected(self):
        folder = "install_config_wizard/maui"
        msi = self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64.msi")
        with (msi.parent / "SHA256SUMS.txt").open("a", encoding="utf-8") as stream:
            stream.write(f"{'0' * 64}  ../outside.cab\n")
        with self.assertRaisesRegex(ValueError, "filename"):
            FEED.build_feed(self.root)

    def test_hash_drift_warns_and_records_actual_bytes(self):
        folder = "install_config_wizard/maui"
        msi = self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64.msi")
        self.package(folder, "ESAIF.ConfigWizard-1.0.1-win-x64-1.cab")
        msi.write_bytes(b"new installer")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            release = FEED.build_feed(self.root)["apps"]["esaif-configwizard"]["platforms"]["windows-x64"]
        self.assertTrue(any("SHA256" in str(item.message) for item in captured))
        self.assertEqual(len(b"new installer"), release["files"][0]["bytes"])
        self.assertEqual(hashlib.sha256(b"new installer").hexdigest(), release["files"][0]["sha256"])

    def test_tkinter_preserves_independent_platform_versions(self):
        folder = self.root / "install_config_wizard"
        artifacts = []
        for platform, architecture, version, archive in (
            ("windows", "AMD64", "v0.47.105", "aifactory-config-windows.zip"),
            ("linux", "x86_64", "v0.47.36", "aifactory-config-linux.tar.gz"),
            ("macos", "arm64", "v0.47.36", "aifactory-config-macos.tar.gz"),
        ):
            self.package(f"install_config_wizard/{platform}", archive)
            artifacts.append({"platform": platform, "architecture": architecture, "version": version,
                              "archive": archive, "bytes": 9, "sha256": hashlib.sha256(b"installer").hexdigest()})
        (folder / "release-manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
        releases = FEED.build_feed(self.root)["apps"]["aifactory-config"]["platforms"]
        self.assertEqual("0.47.105", releases["windows-x64"]["version"])
        self.assertEqual("aifactory-config/aifactory-config.exe", releases["windows-x64"]["entryPoint"])
        self.assertEqual("0.47.36", releases["macos-arm64"]["version"])
        self.assertEqual("tar.gz", releases["linux-x64"]["installerType"])

    def test_version_rejects_non_release_and_non_numeric_strings(self):
        for value in ("1.0.0-beta", "../1.0.0", "latest", "", "1.0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FEED.normalized_version(value)
        self.assertEqual("1.2.10", FEED.normalized_version("v1.2.10"))

    def test_windows_only_publication_uses_updated_platform_manifest(self):
        wizard = self.root / "install_config_wizard"
        self.package("install_config_wizard/windows", "aifactory-config-windows.zip")
        artifact = {"platform": "windows", "architecture": "AMD64", "version": "v0.47.105",
                    "archive": "aifactory-config-windows.zip", "bytes": 9,
                    "sha256": hashlib.sha256(b"installer").hexdigest()}
        (wizard / "release-manifest.json").write_text(json.dumps({"artifacts": [artifact]}), encoding="utf-8")
        updated = {**artifact, "version": "v0.47.106"}
        (wizard / "windows" / "release-manifest.json").write_text(json.dumps(updated), encoding="utf-8")
        with self.assertWarnsRegex(UserWarning, "platform-specific"):
            release = FEED.build_feed(self.root)["apps"]["aifactory-config"]["platforms"]["windows-x64"]
        self.assertEqual("0.47.106", release["version"])

    def test_platform_only_release_does_not_require_aggregate_manifest(self):
        self.package("install_config_wizard/windows", "aifactory-config-windows.zip")
        manifest = self.root / "install_config_wizard" / "windows" / "release-manifest.json"
        manifest.write_text(json.dumps({
            "platform": "windows", "architecture": "AMD64", "version": "v0.47.106",
            "archive": "aifactory-config-windows.zip", "bytes": 9,
            "sha256": hashlib.sha256(b"installer").hexdigest(),
        }), encoding="utf-8")
        release = FEED.build_feed(self.root)["apps"]["aifactory-config"]["platforms"]["windows-x64"]
        self.assertEqual("0.47.106", release["version"])

    def test_atomic_write_has_no_temporary_leftovers(self):
        output = FEED.write_feed(self.root)
        self.assertEqual(FEED.build_feed(self.root), json.loads(output.read_text(encoding="utf-8")))
        self.assertEqual(["app-updates.json"], [path.name for path in self.root.iterdir()])

    def test_ambiguous_same_version_packages_require_publisher_decision(self):
        folder = "install_tutorial_guide"
        for signing in ("signed", "unsigned"):
            stem = f"ESAF-Tutorials-0.2.3-win-x64-local-preview-{signing}"
            self.package(folder, f"{stem}.msi")
            self.package(folder, f"{stem}-1.cab")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            FEED.build_feed(self.root)

    def test_failed_generation_does_not_replace_previous_feed(self):
        previous = FEED.write_feed(self.root).read_bytes()
        self.package("install_config_wizard/maui", "ESAIF.ConfigWizard-1.0.1-win-x64.msi")
        with self.assertRaises(ValueError):
            FEED.write_feed(self.root)
        self.assertEqual(previous, (self.root / "app-updates.json").read_bytes())


class PublishedAppUpdateFeedTests(unittest.TestCase):
    def test_committed_feed_describes_real_complete_releases(self):
        committed = json.loads((SETUP / "app-updates.json").read_text(encoding="utf-8"))
        self.assertEqual(FEED.build_feed(SETUP), committed)


if __name__ == "__main__":
    unittest.main()
