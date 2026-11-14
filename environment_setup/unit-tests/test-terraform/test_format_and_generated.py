"""Static hygiene of the Terraform port: formatting, generated files, no state or working directories."""
from __future__ import annotations

import subprocess
import sys

from harness import MODULES, REPO_ROOT, TERRAFORM_DIR, terraform


def test_terraform_files_are_formatted():
    result = terraform("fmt", "-check", "-recursive", "-no-color", cwd=TERRAFORM_DIR)
    assert result.returncode == 0, f"terraform fmt -recursive would change:\n{result.stdout}{result.stderr}"


def test_arm_unique_string_module_is_generated_from_the_current_generator():
    result = subprocess.run([sys.executable, str(TERRAFORM_DIR / "tools" / "generate_arm_unique_string.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_stage_parameters_are_generated_from_the_current_bicep_parameters():
    result = subprocess.run([sys.executable, str(TERRAFORM_DIR / "tools" / "generate_stage_parameters.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout


def test_no_state_plans_lock_files_or_working_directories_are_tracked():
    tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--", str(TERRAFORM_DIR)],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    assert tracked, "the Terraform port is not tracked"
    offending = [name for name in tracked if "/.terraform/" in name or name.endswith((".tfstate", ".tfplan"))
                 or ".tfstate." in name or name.endswith(".tfvars")]
    assert not offending, offending


def test_terraform_sources_are_committed_with_lf_line_endings_and_utf8():
    """The committed blobs (git's index), not the working tree: a Windows checkout may convert to CRLF."""
    listing = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--eol", "--", str(TERRAFORM_DIR),
                              str(TERRAFORM_DIR.parents[1] / "unit-tests" / "test-terraform")],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    assert listing
    for line in listing:
        index_eol, path = line.split()[0], line.split("\t", 1)[1]
        assert index_eol in ("i/lf", "i/none", "i/-text"), f"{path} is committed with {index_eol}"
    for path in TERRAFORM_DIR.rglob("*"):
        if path.is_file() and ".terraform" not in path.parts and path.suffix in (".tf", ".hcl", ".py", ".md", ".json", ".yml"):
            path.read_bytes().decode("utf-8")


def test_every_module_has_the_standard_files_and_names_its_bicep_source():
    for module in sorted(path for path in MODULES.iterdir() if path.is_dir()):
        names = {path.name for path in module.glob("*.tf")}
        assert {"main.tf", "versions.tf"} <= names, f"{module.name}: {sorted(names)}"
        header = (module / "main.tf").read_text(encoding="utf-8").splitlines()[:6]
        assert any("bicep" in line.lower() or "uniqueString" in line or "naming convention" in line
                   for line in header), f"{module.name}/main.tf must name the Bicep it ports in its header"
        assert not list(module.glob("*.tf.json")), module.name
        for tf in module.glob("*.tf"):
            assert 'provider "' not in tf.read_text(encoding="utf-8"), f"{tf}: modules never configure providers"
