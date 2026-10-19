"""Offline checks that the Tkinter wizard download links match one published desktop release."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[4]
WIZARD = ROOT / "environment_setup" / "install_config_wizard"
RELEASES = "https://github.com/jostrm/azure-enterprise-scale-ml/releases"
DESKTOP_LINK = re.compile(re.escape(RELEASES) + r"/(?:tag|download)/(desktop-v[^/)\s]+)(?:/([^)\s]+))?")
PROVENANCE = {"SHA256SUMS.txt", "release-manifest.json"}


class InstallConfigWizardDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (WIZARD / "readme.md").read_text(encoding="utf-8")
        cls.manifest = json.loads((WIZARD / "release-manifest.json").read_text(encoding="utf-8"))
        cls.checksums = (WIZARD / "SHA256SUMS.txt").read_text(encoding="utf-8")
        cls.links = DESKTOP_LINK.findall(cls.readme)

    def test_readme_links_only_the_release_described_by_the_manifest(self):
        self.assertTrue(self.links)
        self.assertEqual({tag for tag, _ in self.links}, {f"desktop-{self.manifest['version']}"})
        heading = re.search(r"^## Download - Version `([^`]+)`$", self.readme, re.M)
        self.assertIsNotNone(heading)
        self.assertEqual(f"v{heading.group(1)}", self.manifest["version"])

    def test_readme_links_every_archive_and_provenance_file_by_exact_name(self):
        archives = {artifact["archive"] for artifact in self.manifest["artifacts"]}
        self.assertEqual({"aifactory-config-windows.zip", "aifactory-config-linux.tar.gz",
                          "aifactory-config-macos.tar.gz"}, archives)
        self.assertEqual(archives | PROVENANCE, {asset for _, asset in self.links if asset})

    def test_manifest_artifacts_come_from_one_build(self):
        for field in ("version", "source_commit"):
            self.assertEqual({artifact[field] for artifact in self.manifest["artifacts"]}, {self.manifest[field]})
        for field in ("accelerator_commit", "run_id"):
            self.assertEqual(len({artifact[field] for artifact in self.manifest["artifacts"]}), 1, field)

    def test_checksums_match_the_manifest(self):
        listed = {}
        for line in self.checksums.splitlines():
            digest, name = line.split("  ", 1)
            listed[name] = digest
        self.assertEqual({artifact["archive"]: artifact["sha256"] for artifact in self.manifest["artifacts"]}, listed)

    def test_maui_readme_links_no_other_desktop_release(self):
        maui = (WIZARD / "maui" / "readme.md").read_text(encoding="utf-8")
        tags = {tag for tag, _ in DESKTOP_LINK.findall(maui)}
        self.assertLessEqual(tags, {f"desktop-{self.manifest['version']}"})

    def test_readme_does_not_download_the_legacy_archives_kept_on_main(self):
        legacy = re.findall(r"raw/refs/heads/main/environment_setup/install_config_wizard/\w+/[^)\s]+"
                            r"|tar -xzf (?:linux|macos)/\S+", self.readme)
        self.assertEqual([], legacy)


if __name__ == "__main__":
    unittest.main()
