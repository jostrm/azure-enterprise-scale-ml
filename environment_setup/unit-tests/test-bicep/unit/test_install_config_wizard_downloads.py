"""Offline checks that the Tkinter wizard downloads are the archives committed beside its readme."""

import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[4]
WIZARD = ROOT / "environment_setup" / "install_config_wizard"
RAW_MAIN = "https://github.com/jostrm/azure-enterprise-scale-ml/raw/refs/heads/main/environment_setup/install_config_wizard/"
RAW_LINK = re.compile(re.escape(RAW_MAIN) + r"([^)\s]+)")
FOLDERS = {"aifactory-config-windows.zip": "windows", "aifactory-config-linux.tar.gz": "linux",
           "aifactory-config-macos.tar.gz": "macos"}
DESKTOP_RELEASE = re.compile(r"releases/(?:tag|download)/desktop-v")
# Live links only: relative paths and blob/main URLs. Permalinks pinned to a commit keep their history.
MAUI_README_LINK = re.compile(r"\]\((?!https?://)[^)\s]*maui/readme\.md"
                              r"|blob/main/environment_setup/install_config_wizard/maui/readme\.md")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checksums(path):
    listed = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    return listed


class InstallConfigWizardDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (WIZARD / "readme.md").read_text(encoding="utf-8")
        cls.manifest = json.loads((WIZARD / "release-manifest.json").read_text(encoding="utf-8"))
        cls.artifacts = {artifact["archive"]: artifact for artifact in cls.manifest["artifacts"]}

    def test_each_download_row_names_its_archive_version(self):
        # Regular pink releases build Windows only (AIF_RELEASE_PLATFORMS=windows), so platforms may differ in version.
        self.assertIsNotNone(re.search(r"^## Download$", self.readme, re.M))
        for archive, folder in FOLDERS.items():
            rows = [line for line in self.readme.splitlines() if line.startswith("|") and f"{folder}/{archive})" in line]
            self.assertEqual(1, len(rows), archive)
            self.assertIn(f"| {self.artifacts[archive]['version']},", rows[0], archive)

    def test_readme_downloads_every_archive_from_its_folder_on_main(self):
        self.assertEqual(set(FOLDERS), set(self.artifacts))
        self.assertEqual({f"{folder}/{archive}" for archive, folder in FOLDERS.items()},
                         set(RAW_LINK.findall(self.readme)))

    def test_readme_links_the_provenance_files_beside_it(self):
        for name in ("SHA256SUMS.txt", "release-manifest.json"):
            self.assertIn(f"]({name})", self.readme)

    def test_committed_archives_are_the_manifest_builds(self):
        for archive, folder in FOLDERS.items():
            path = WIZARD / folder / archive
            self.assertEqual(self.artifacts[archive]["bytes"], path.stat().st_size, archive)
            self.assertEqual(self.artifacts[archive]["sha256"], sha256(path), archive)

    def test_each_artifact_carries_its_own_build_provenance(self):
        self.assertEqual(set(self.manifest), {"artifacts"})
        for artifact in self.manifest["artifacts"]:
            self.assertRegex(artifact["version"], r"^v\d+\.\d+\.\d+$")
            for field in ("source_commit", "accelerator_commit"):
                self.assertRegex(artifact[field], r"^[0-9a-f]{40}$")
            self.assertRegex(artifact["run_id"], r"^\d+$")

    def test_checksums_match_the_manifest(self):
        self.assertEqual({archive: artifact["sha256"] for archive, artifact in self.artifacts.items()},
                         checksums(WIZARD / "SHA256SUMS.txt"))

    def test_windows_folder_provenance_describes_the_committed_zip(self):
        windows = self.artifacts["aifactory-config-windows.zip"]
        self.assertEqual(windows, json.loads((WIZARD / "windows" / "release-manifest.json").read_text(encoding="utf-8")))
        self.assertEqual({windows["archive"]: windows["sha256"]}, checksums(WIZARD / "windows" / "SHA256SUMS.txt"))

    def test_wizard_readmes_link_no_desktop_release(self):
        for readme in (WIZARD / "readme.md", WIZARD / "maui" / "readme.md"):
            self.assertIsNone(DESKTOP_RELEASE.search(readme.read_text(encoding="utf-8")), readme)

    def test_docs_link_the_wizard_page_instead_of_the_maui_readme(self):
        pages = [*ROOT.glob("*.md"), *(ROOT / "documentation").rglob("*.md"), *WIZARD.rglob("*.md")]
        linked = [str(page.relative_to(ROOT)) for page in pages
                  if MAUI_README_LINK.search(page.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual([], linked)


if __name__ == "__main__":
    unittest.main()
