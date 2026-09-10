"""Legacy entrypoints cannot silently reinterpret scoped creation as project001."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BASH = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
if not BASH.is_file():
    BASH = shutil.which("bash")


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("name,value", [
    ("AIF_CREATE_PROJECTS", "none"), ("AIF_CREATE_PROJECTS", "all"), ("AIF_PROJECT_MODE", "none"),
])
def test_scoped_creation_settings_fail_before_legacy_defaults_or_auth(name, value):
    env = {key: content for key, content in os.environ.items()
           if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "HOME", "USERPROFILE",
                              "TEMP", "TMP", "LOCALAPPDATA", "PROGRAMFILES"}}
    env[name] = value
    script = r'''
source bootstrap/lib/create-new-aifactory-scaleset.sh
aif_simple_stage() { printf 'FORBIDDEN_LEGACY_STAGE\n'; return 91; }
aif_collect_answers() { printf 'FORBIDDEN_PROJECT_DEFAULT\n'; return 92; }
aif_scaleset_main gha "$PWD/bootstrap/GHA-create-new-aifactory-scaleset.sh" --non-interactive --yes
'''
    result = subprocess.run([str(BASH), "--noprofile", "--norc", "-c", script],
                            cwd=ROOT, env=env, input="", capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode != 0
    assert "AIFactory-lifecycle.sh" in result.stderr
    assert "no implicit project001 fallback" in result.stderr
    assert "FORBIDDEN_" not in result.stdout
