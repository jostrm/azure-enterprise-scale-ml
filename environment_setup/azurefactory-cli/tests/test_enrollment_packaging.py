"""Offline wheel/sdist installation contract, using only existing build tooling."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]


def run(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-6000:]
    return result.stdout


def test_wheel_and_sdist_install_with_bundled_canonical_core_outside_source(tmp_path):
    pytest.importorskip("setuptools")
    pytest.importorskip("wheel")
    source = tmp_path / "source"
    package = source / "environment_setup" / "azurefactory-cli"
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(
        "__pycache__", ".pytest_cache", "*.egg-info", "build", "dist", ".venv"))
    helper = source / "bootstrap" / "lib" / "factory_enrollment.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes((ROOT / "bootstrap" / "lib" / "factory_enrollment.py").read_bytes())
    dist = tmp_path / "distributions"
    scratch = tmp_path / "build-scratch"
    scratch.mkdir()
    env = dict(os.environ, TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch),
               PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    env.pop("PYTHONPATH", None)
    run([sys.executable, "setup.py", "--quiet", "sdist", "--dist-dir", str(dist),
         "bdist_wheel", "--dist-dir", str(dist)], package, env)
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("azurefactory/_vendor/factory_enrollment.py") == helper.read_bytes()
    with tarfile.open(sdist) as archive:
        name = next(name for name in archive.getnames() if name.endswith("/src/azurefactory/_vendor/factory_enrollment.py"))
        assert archive.extractfile(name).read() == helper.read_bytes()
    outside = tmp_path / "outside-source"
    outside.mkdir()
    for kind, artifact in (("wheel", wheel), ("sdist", sdist)):
        installed = tmp_path / ("installed-" + kind)
        # The host's existing pip/setuptools are reused; no build dependencies are downloaded.
        venv.EnvBuilder(with_pip=False, system_site_packages=True).create(installed)
        scripts = installed / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        run([str(python), "-m", "pip", "install", "--no-deps", "--no-build-isolation", "--no-cache-dir",
             str(artifact)], outside, env)
        executable = scripts / ("azurefactory.exe" if os.name == "nt" else "azurefactory")
        output = run([str(executable), "enrollment", "--help"], outside, env)
        assert "prepare-binding" in output and "ensure" in output
        run([str(executable), "enrollment", "ensure", "--help"], outside, env)
        location = run([str(python), "-c",
                        "from azurefactory.enrollment import core; print(core().__file__)"], outside, env).strip()
        assert Path(location).is_relative_to(installed)
        assert Path(location).read_bytes() == helper.read_bytes()
