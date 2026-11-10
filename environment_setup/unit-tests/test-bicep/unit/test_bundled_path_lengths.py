"""Paths under environment_setup must stay short enough for Windows installers.

The pink Factory API bundles this tree, and the MAUI ConfigWizard and TutorialApp ship that bundle in an MSI.
Windows Installer refuses any file path above MAX_PATH (260 characters, Error 1320), and WiX's native cabinet
builder dies on them ("The pipe is being closed"). The installed path is
``%LOCALAPPDATA%\\Programs\\ESAIF.ConfigWizard\\ApiHost\\_internal\\accelerator\\<repo path>``: for the user name
``jostrm`` the root is 87 characters, so a 160-character repo path leaves 13 characters for longer user names.
On 2026-11-10 ``copy_to_local_settings/automation/coreteam/finops/logicapps/aimodel-throttling-via-networkrule``
reached 177 characters and blocked the ConfigWizard 1.0.24 MSI.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[4]
MAX_REPO_PATH = 160


def _tracked_files():
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "environment_setup"],
                            capture_output=True, check=True)
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


def test_environment_setup_paths_fit_a_windows_installer():
    files = _tracked_files()
    assert files, "git ls-files found no environment_setup files"
    too_long = sorted((len(name), name) for name in files if len(name) > MAX_REPO_PATH)
    assert not too_long, (
        f"{len(too_long)} path(s) exceed {MAX_REPO_PATH} characters and break the MSI that bundles them:\n"
        + "\n".join(f"{length}: {name}" for length, name in too_long))
