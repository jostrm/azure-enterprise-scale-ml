#!/usr/bin/env python3
"""Run every component test suite of the AI Factory accelerator ("purple") on one worktree.

Usage:
    run_component_suites.py --worktree <path> --results <dir>
                            [--only id1,id2] [--skip-install] [--install-only]
                            [--rerun-failing] [--clean-created] [--list]

Standard library only.  The main IaC suite (environment_setup/unit-tests/test-bicep) is NOT
part of this runner.

Design rules
------------
* One virtual environment per suite, /home/user/venvs/<id> (override: --venvs or
  COMPONENT_VENVS).  Environments hold third-party dependencies ONLY.  No package of the
  repository is ever installed into a venv (neither editable nor as a wheel): the code under
  test is always imported from the given worktree, through the component's own pytest
  ``pythonpath``/conftest logic or through the PYTHONPATH this runner sets.  Nothing is
  therefore written into the worktree by an install, and a venv can be reused for another
  worktree.
* A venv is rebuilt from scratch when its stamp differs: the stamp hashes the Python version,
  the install recipe and the bytes of the worktree's requirement inputs (requirements*.txt,
  lock files, pyproject.toml).  Same inputs -> same venv, different inputs -> clean rebuild.
* Every test command is wrapped in /home/user/tools/cienv.sh (COMPONENT_CI_WRAPPER):
  `cienv.sh <venv>/bin -- [env VAR=value ...] <command>`.  The wrapper starts from an empty environment
  (env -i): no proxy variables, no injected tokens, neutral git configuration, LIVE_AZURE=0, PYTHONUTF8=1,
  PYTHONDONTWRITEBYTECODE=1, PATH = <venv>/bin, Bicep, PowerShell, offline Azure CLI, Node, system folders.
  There is no Azure login.  Suite specific variables (PYTHONPATH into the worktree, TIKTOKEN_CACHE_DIR)
  go inside the wrapped command and are listed per suite in summary.json (suite_variables), together with
  the complete environment the command saw (effective_environment).  Install commands are not wrapped.
  --no-wrapper runs the command in the inherited environment instead (proxy variables and injected tokens
  kept; Bicep, PowerShell and Node on PATH, no Azure CLI), which is how the first baseline runs were made.
* Suites run strictly one after the other.  A test command is killed after its timeout
  (default 2700 s) and reported as "timeout", never as pass.
* The worktree is never modified by the runner.  `git status --porcelain --ignored` is
  compared before/after each suite and new paths are reported per suite
  (--clean-created removes only new untracked/ignored paths under the suite's own folders).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

RECIPE_VERSION = "7"
DEFAULT_VENVS = Path(os.environ.get("COMPONENT_VENVS", "/home/user/venvs"))
TOOL_DIRS = [p for p in os.environ.get(
    "COMPONENT_TOOL_DIRS", "/home/user/tools/bicep:/home/user/tools/pwsh:/opt/node22/bin").split(":") if p]
# Every TEST command is wrapped in this script (usage: cienv.sh <dir to prepend to PATH> -- command ...): it runs
# the command with `env -i` and a minimal CI-like environment (no proxy variables, no injected tokens, neutral git
# configuration, LIVE_AZURE=0, PYTHONUTF8=1, PYTHONDONTWRITEBYTECODE=1, PATH = <venv bin>, Bicep, PowerShell,
# offline Azure CLI, Node, system folders).  Suite specific variables are passed as `env VAR=value` inside the
# wrapped command.  Install commands are NOT wrapped (they need the proxy).  --no-wrapper uses the inherited
# environment (test_env) instead.
CI_WRAPPER = os.environ.get("COMPONENT_CI_WRAPPER", "/home/user/tools/cienv.sh")
UV = shutil.which("uv") or "/root/.local/bin/uv"
DEFAULT_TIMEOUT = 2700
PYTEST_FLAGS = ["--tb=short", "-p", "no:cacheprovider"]

AF = "usecase_code/40-agent-factory"
MF = "usecase_code/50-ml-model-factory"
CLI = "environment_setup/azurefactory-cli"
AUTOMATION = "environment_setup/aifactory/bicep/copy_to_local_settings/automation"
MLOPS = "copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09"
ADF = "copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory"
VOICE = AF + "/40-foundry-voice-sales--from-fabric"
RAG48 = AF + "/48-rag-with-splitted-tables-acl-adlsgen2"
ML49 = AF + "/49-agent-training-ml-churn-prediction"
AGENT = AF + "/40-aifactory-agent"
FUNC = "usecase_code/10-azure-function/12_func_aifactory_lifecycle"
WIZ = "environment_setup/install_config_wizard/api-usage-examples"
ONION = "documentation/v2/10-19/images/onion"
TUTORIAL = "environment_setup/install_tutorial_guide"

PIP = ["{uv}", "pip", "install", "--python", "{py}"]
PYTEST_PIN = "pytest>=8,<10"


def pip(*args):
    return PIP + list(args)


PINNED_SDK_RX = re.compile(r"^azurefactory-cli\s*@\s*git\+(https://[^@\s]+)@([0-9a-f]{40})#subdirectory=(\S+)$")


def _func_requirements(worktree):
    """Requirement lines of the lifecycle Function (requirements.txt + requirements-dev.txt) and its pinned SDK."""
    plain, pinned = [], None
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (Path(worktree) / FUNC / name).read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or text.startswith("-r"):
                continue
            match = PINNED_SDK_RX.match(text)
            if match:
                pinned = match.groups()
            elif text.lower().startswith("azurefactory-cli"):
                raise ValueError("unexpected azurefactory-cli requirement: " + text)
            else:
                plain.append(text)
    return plain, pinned


def install_func_requirements_without_sdk(ctx, log, env):
    """requirements-dev.txt minus the azurefactory-cli line (the SDK then comes from the worktree)."""
    plain, _ = _func_requirements(ctx["wt"])
    return run_logged([UV, "pip", "install", "--python", str(ctx["py"]), *plain], log, env)


def install_func_requirements_pinned_sdk_sparse(ctx, log, env):
    """requirements-dev.txt; the git-pinned azurefactory-cli is built from a shallow, sparse checkout of that commit.

    Same commit and subdirectory as the requirement line, but only the two folders its setup.py reads are
    downloaded (the full history of the repository is several hundred MB).
    """
    plain, pinned = _func_requirements(ctx["wt"])
    if not pinned:
        log.write("no git-pinned azurefactory-cli requirement found\n")
        return 1
    url, sha, subdirectory = pinned
    checkout = Path(ctx["venvs"]) / ".cache" / ("azurefactory-cli-" + sha)
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0 or head.stdout.strip() != sha:
        shutil.rmtree(checkout, ignore_errors=True)
        checkout.mkdir(parents=True)
        for argv in (["git", "init", "-q", "."], ["git", "remote", "add", "origin", url],
                     ["git", "config", "remote.origin.promisor", "true"],
                     ["git", "config", "remote.origin.partialclonefilter", "blob:none"],
                     ["git", "sparse-checkout", "set", "--cone", subdirectory, "bootstrap/lib"],
                     ["git", "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", sha],
                     ["git", "checkout", "-q", "--detach", "FETCH_HEAD"]):
            if run_logged(argv, log, env, cwd=str(checkout), timeout=600) != 0:
                return 1
    return run_logged([UV, "pip", "install", "--python", str(ctx["py"]), *plain, str(checkout / subdirectory)], log, env)



SIX = {"name": "six (azure-ai-ml 1.34.x imports it without declaring it; python-dateutil 4 no longer pulls it in, "
               "so `import azure.ai.ml` fails without this)",
       "alternatives": [pip("six")]}
MF_DEPS = [{"name": "model-factory dependencies [train,azure,dev] as in the readme, plus the `kaggle` extra "
                    "(test_lifecycle_e2e/test_tags import kagglehub unconditionally); dependencies only, no project install",
            "alternatives": [pip("-r", "{wt}/" + MF + "/pyproject.toml",
                                 "--extra", "train", "--extra", "azure", "--extra", "dev", "--extra", "kaggle")]},
           SIX,
           {"name": "build-system requirement of the model-factory pyproject.toml (test_layout imports setuptools)",
            "alternatives": [pip("setuptools>=75", "wheel")]}]

# ---------------------------------------------------------------------------------------------
# Suite table.  Paths are relative to the worktree root.  Placeholders: {wt} {venv} {py} {uv}.
#   kind      pytest | node | pwsh | not-run
#   files     [(folder, regex on the path below the folder)] -> "test files" count (git ls-files)
#   inputs    worktree files hashed into the venv stamp
#   install   steps; each step lists alternatives, the first that succeeds wins
#   test      argv of the repo's own command (the runner appends its pytest flags)
#   pythonpath  worktree folders put on PYTHONPATH (instead of `pip install -e`)
# ---------------------------------------------------------------------------------------------
SUITES = [
    {
        "id": "azurefactory-cli", "kind": "pytest", "component": CLI, "cwd": ".", "python": "3.12",
        "files": [(CLI + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [CLI + "/pyproject.toml", ".github/workflows/deploy-docs.yml"],
        "install": [{"name": "pytest + mkdocs-material (as .github/workflows/deploy-docs.yml) + setuptools/wheel "
                             "(build tooling used by test_enrollment_packaging; otherwise that test skips)",
                     "alternatives": [pip(PYTEST_PIN, "mkdocs-material", "setuptools", "wheel")]}],
        "pythonpath": [CLI + "/src"],
        "test": ["{py}", "-m", "pytest", CLI + "/tests"],
        "repo_command": "python -m pytest environment_setup/azurefactory-cli/tests/<files> -q  (deploy-docs.yml, repo root); "
                        "readme: pip install -e .",
        "notes": "Package has no dependencies; azurefactory comes from <worktree>/src (tests/conftest.py + PYTHONPATH).",
    },
    {
        "id": "graphify", "kind": "pytest", "component": "environment_setup/graphify", "cwd": ".", "python": "3.12",
        "files": [("environment_setup/graphify/tests", r"^test_[^/]*\.py$")],
        "inputs": ["environment_setup/graphify/requirements.txt", "environment_setup/graphify/requirements.lock.txt"],
        "install": [{"name": "graphify requirements",
                     "alternatives": [
                         pip("-r", "{wt}/environment_setup/graphify/requirements.lock.txt"),
                         pip("-r", "{wt}/environment_setup/graphify/requirements.txt",
                             "-c", "{wt}/environment_setup/graphify/requirements.lock.txt"),
                         pip("-r", "{wt}/environment_setup/graphify/requirements.txt")]}],
        "test": ["{py}", "-m", "pytest", "environment_setup/graphify/tests"],
        "repo_command": "no documented test command; environment per documentation/architecture/contracts/"
                        "dual-graph-lifecycle.md (uv venv --python 3.12; pip install -r requirements.lock.txt), repo root",
    },
    {
        "id": "wizard-api-usage-examples", "kind": "pytest", "component": WIZ, "cwd": WIZ, "python": "3.12",
        "files": [(WIZ + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [CLI + "/pyproject.toml"],
        "install": [{"name": "pytest (no requirements file; SDK is stdlib only)", "alternatives": [pip(PYTEST_PIN)]}],
        "pythonpath": [CLI + "/src"],
        "test": ["{py}", "-m", "pytest", "./tests"],
        "repo_command": r"python -m pytest .\tests ..\..\azurefactory-cli\tests\test_{cli,client,reviews,quickstart_examples}.py "
                        r"-q --basetemp .local\pytest-work  (readme, from this folder)",
        "notes": "Deviation: the four azurefactory-cli files of the readme command run in suite azurefactory-cli, and "
                 "--basetemp .local/pytest-work is dropped so that nothing is written into the worktree.",
    },
    {
        "id": "bicep-automation", "kind": "pytest", "component": AUTOMATION, "cwd": AUTOMATION, "python": "3.12",
        "files": [(AUTOMATION, r"(^|/)test_[^/]*\.py$")],
        "inputs": [],
        "install": [{"name": "pytest (no requirements file for these tests)", "alternatives": [pip(PYTEST_PIN)]}],
        "test": ["{py}", "-m", "pytest", "."],
        "repo_command": "no documented command; tests import sibling modules, so they run from the automation folder",
    },
    {
        "id": "esml-v2", "kind": "pytest", "component": "esml-v2", "cwd": "esml-v2", "python": "3.12",
        "files": [("esml-v2/tests", r"^test_[^/]*\.py$")],
        "inputs": ["esml-v2/pyproject.toml"],
        "install": [{"name": "esml-v2 dependencies [train,storage,dev] (dependencies only, no project install)",
                     "alternatives": [pip("-r", "{wt}/esml-v2/pyproject.toml",
                                          "--extra", "train", "--extra", "storage", "--extra", "dev")]},
                    SIX,
                    {"name": "Pillow, version range of the `vision` extra (tests/test_lake_modalities.py imports PIL "
                             "unconditionally; the torch packages of that extra are not installed)",
                     "alternatives": [pip("Pillow>=11,<13")]},
                    {"name": "build-system requirements of esml-v2/pyproject.toml (tests/test_esml_packaging.py imports "
                             "setuptools and drives the esml_build backend)",
                     "alternatives": [pip("setuptools>=77", "wheel")]}],
        "pythonpath": ["esml-v2", MF + "/accelerator/src"],
        "test": ["{py}", "-m", "pytest"],
        "notes": "PYTHONPATH = what an installed azure-esml-sdk provides (azure_esml + bundled ml_model_factory), taken "
                 "from the worktree: one test starts `python -m azure_esml.domain_layer.runtime` as a subprocess, which "
                 "does not see pytest's own pythonpath setting.",
        "repo_command": "python -m pytest from esml-v2 ([tool.pytest.ini_options] testpaths=tests, "
                        "pythonpath=., ../usecase_code/50-ml-model-factory/accelerator/src)",
    },
    {
        "id": "healthmodel", "kind": "pytest", "component": "healthmodel", "cwd": "healthmodel", "python": "3.12",
        "files": [("healthmodel/tests", r"^test_[^/]*\.py$")],
        "inputs": ["healthmodel/pyproject.toml"],
        "install": [{"name": "healthmodel dependencies [test] (dependencies only, no project install)",
                     "alternatives": [pip("-r", "{wt}/healthmodel/pyproject.toml", "--extra", "test")]}],
        "test": ["{py}", "-m", "pytest"],
        "quiet_in_config": True,
        "repo_command": "cd healthmodel; python -m pytest  (readme section 14; addopts=-q, pythonpath=src,tests; "
                        "live tests opt in with AIF_HEALTHMODEL_LIVE=1)",
    },
    {
        "id": "mcp", "kind": "pytest", "component": "mcp", "cwd": "mcp", "python": "3.12",
        "files": [("mcp/tests", r"^test_[^/]*\.py$")],
        "inputs": ["mcp/pyproject.toml", "mcp/deploy/requirements.linux.lock.txt", "mcp/deploy/requirements.mcp.txt",
                   AGENT + "/requirements.txt"],
        "install": [
            {"name": "mcp + agent runtime dependencies",
             "alternatives": [
                 pip("-r", "{wt}/mcp/deploy/requirements.linux.lock.txt"),
                 pip("-r", "{wt}/" + AGENT + "/requirements.txt", "-r", "{wt}/mcp/pyproject.toml",
                     "-c", "{wt}/mcp/deploy/requirements.linux.lock.txt"),
                 pip("-r", "{wt}/" + AGENT + "/requirements.txt", "-r", "{wt}/mcp/pyproject.toml")]},
            {"name": "pytest (dev extra of mcp/pyproject.toml)", "alternatives": [pip(PYTEST_PIN)]}],
        "pythonpath": ["mcp/src", CLI + "/src"],
        "test": ["{py}", "-m", "pytest"],
        "repo_command": "& $Python -m pytest -q from mcp (readme); install: pip install -r ../usecase_code/40-agent-factory/"
                        "40-aifactory-agent/requirements.txt -e ../environment_setup/azurefactory-cli -e .[dev]",
    },
    {
        "id": "func-aifactory-lifecycle", "kind": "pytest", "component": FUNC, "cwd": FUNC, "python": "3.12",
        "files": [(FUNC + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [FUNC + "/requirements.txt", FUNC + "/requirements-dev.txt"],
        "install": [{"name": "requirements-dev.txt (includes the azurefactory-cli SDK pinned to a GitHub commit)",
                     "alternatives": [install_func_requirements_pinned_sdk_sparse,
                                      pip("-r", "{wt}/" + FUNC + "/requirements-dev.txt")]}],
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": r"python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt (README); pytest from the folder",
        "notes": "As the component declares it: the azurefactory SDK is the commit pinned in requirements.txt, fetched "
                 "from GitHub at venv build time, NOT the worktree's SDK (tests/conftest.py prefers an installed SDK).",
    },
    {
        "id": "func-aifactory-lifecycle-wt-sdk", "kind": "pytest", "component": FUNC, "cwd": FUNC, "python": "3.12",
        "files": [(FUNC + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [FUNC + "/requirements.txt", FUNC + "/requirements-dev.txt"],
        "install": [{"name": "requirements-dev.txt without the pinned azurefactory-cli git dependency",
                     "alternatives": [install_func_requirements_without_sdk]}],
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": "variant of func-aifactory-lifecycle: tests/conftest.py falls back to the SDK of the accelerator "
                        "checkout when azurefactory is not installed",
        "notes": "Same tests, but the azurefactory SDK comes from <worktree>/environment_setup/azurefactory-cli/src "
                 "(conftest fallback), so SDK changes of the worktree are exercised.",
    },
    {
        "id": "agent-factory", "kind": "pytest", "component": AF, "cwd": AF, "python": "3.13",
        "files": [(AF + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [AF + "/requirements.txt"],
        "install": [{"name": "operator requirements.txt", "alternatives": [pip("-r", "{wt}/" + AF + "/requirements.txt")]},
                    {"name": "pytest (not in requirements.txt; repo runner is unittest) + PyYAML "
                             "(optional YAML contract checks, tests/readme.md)",
                     "alternatives": [pip(PYTEST_PIN, "PyYAML")]}],
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": r".\.venv\Scripts\python.exe -m unittest discover -s tests  from 40-agent-factory, Python 3.13 "
                        "(tests/readme.md)",
        "notes": "Documented operator environment only. Three pytest-style tests import 40-aifactory-agent and therefore "
                 "need its runtime (azurefactory SDK, httpx, ...), which requirements.txt does not install; the two "
                 "environments must not be merged according to the agent readme.",
    },
    {
        "id": "aifactory-agent", "kind": "pytest", "component": AGENT, "cwd": AGENT, "python": "3.12",
        "files": [(AGENT + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [AGENT + "/requirements.txt", AGENT + "/requirements.lock.txt"],
        "install": [{"name": "agent requirements",
                     "alternatives": [
                         pip("-r", "{wt}/" + AGENT + "/requirements.lock.txt"),
                         pip("-r", "{wt}/" + AGENT + "/requirements.txt", "-c", "{wt}/" + AGENT + "/requirements.lock.txt"),
                         pip("-r", "{wt}/" + AGENT + "/requirements.txt")]},
                    {"name": "pytest (not in the lock)", "alternatives": [pip(PYTEST_PIN)]}],
        "pythonpath": [CLI + "/src"],
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": r".\.venv\Scripts\python.exe -m pytest -q tests  from 40-aifactory-agent, Python 3.12 (readme); "
                        r"install: pip install -r requirements.lock.txt; pip install -e ..\..\..\environment_setup\azurefactory-cli",
    },
    {
        "id": "voice-sales-py", "kind": "pytest", "component": VOICE, "cwd": VOICE, "python": "3.13",
        "files": [(VOICE + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [VOICE + "/requirements.txt", VOICE + "/requirements.lock.txt"],
        "install": [{"name": "voice-sales requirements",
                     "alternatives": [
                         pip("-r", "{wt}/" + VOICE + "/requirements.lock.txt"),
                         pip("-r", "{wt}/" + VOICE + "/requirements.txt", "-c", "{wt}/" + VOICE + "/requirements.lock.txt"),
                         pip("-r", "{wt}/" + VOICE + "/requirements.txt")]},
                    {"name": "pytest (not in requirements; repo runner is unittest)", "alternatives": [pip(PYTEST_PIN)]}],
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": "Start-FoundryVoiceSales.ps1 -Action Test: python -m unittest discover -s tests -p test_*.py "
                        "(Python 3.13, pip install -r requirements.lock.txt), then node --test tests/frontend*.test.js",
    },
    {
        "id": "voice-sales-frontend-js", "kind": "node", "component": VOICE, "cwd": VOICE,
        "files": [(VOICE + "/tests", r"^frontend[^/]*\.test\.js$")],
        "glob": "tests/frontend*.test.js",
        "repo_command": "npm test = node --test tests/frontend*.test.js (package.json; Node 22, no npm dependencies)",
    },
    {
        "id": "rag-48", "kind": "pytest", "component": RAG48, "cwd": RAG48, "python": "3.13",
        "files": [(RAG48 + "/tests", r"(^|/)test_[^/]*\.py$")],
        "inputs": [RAG48 + "/requirements.txt", AF + "/requirements.txt"],
        "install": [{"name": "requirements.txt (includes ../requirements.txt)",
                     "alternatives": [pip("-r", "{wt}/" + RAG48 + "/requirements.txt")]},
                    {"name": "pytest (not in requirements; repo runner is unittest)", "alternatives": [pip(PYTEST_PIN)]}],
        "env": {"TIKTOKEN_CACHE_DIR": "{venvs}/.cache/tiktoken-cache"},
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": r"& $Python -m unittest discover -s tests  from the folder, Python 3.13, "
                        r"TIKTOKEN_CACHE_DIR=.venv\tiktoken-cache (readme); tests/service and tests/live are unittest "
                        "classes that skip unless AIF48_SERVICE_TESTS / AIF48_GRAPH_SERVICE_TESTS / "
                        "AIF48_LIVE_EVALUATIONS+AIF48_ALLOW_PAID are set",
        "notes": "tiktoken needs the cl100k_base encoding file. It is read from TIKTOKEN_CACHE_DIR "
                 "(<venvs>/.cache/tiktoken-cache, file name 9b5ad71b2ce5302211f9c61530b329a4922fc6a4 = sha1 of "
                 "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken) or downloaded from that URL "
                 "on first use; the runner never downloads it.",
    },
    {
        "id": "ml-churn-49", "kind": "pytest", "component": ML49, "cwd": ML49, "python": "3.13",
        "files": [(ML49 + "/tests", r"(^|/)test_[^/]*\.py$")],
        "inputs": [ML49 + "/requirements.txt", AF + "/requirements.txt", "esml-v2/pyproject.toml"],
        "install": [{"name": "requirements.txt (includes ../requirements.txt)",
                     "alternatives": [pip("-r", "{wt}/" + ML49 + "/requirements.txt")]},
                    {"name": "dependencies of esml-v2[train,storage,dev] (the SDK itself comes from the worktree)",
                     "alternatives": [pip("-r", "{wt}/esml-v2/pyproject.toml",
                                          "--extra", "train", "--extra", "storage", "--extra", "dev")]}, SIX],
        "pythonpath": ["esml-v2", MF + "/accelerator/src"],
        "test": ["{py}", "-m", "pytest", "tests"],
        "repo_command": r'pip install -r requirements.txt "..\..\..\esml-v2[train,storage,dev]"; '
                        r"python -m unittest discover -s tests  (readme); tests/live skips unless AIF49_LIVE=1 and AIF49_CONFIG",
        "notes": "The readme installs the built ESML SDK (bundles ml_model_factory). The runner puts <worktree>/esml-v2 and "
                 "<worktree>/usecase_code/50-ml-model-factory/accelerator/src on PYTHONPATH instead (same sources).",
    },
    {
        "id": "ml-model-factory", "kind": "pytest", "component": MF, "cwd": MF, "python": "3.12",
        "files": [(MF + "/accelerator/tests", r"^test_[^/]*\.py$")],
        "inputs": [MF + "/pyproject.toml", MF + "/setup.cfg"],
        "install": MF_DEPS,
        "pythonpath": [MF + "/accelerator/src"],
        "test": ["{py}", "-m", "pytest"],
        "notes": "PYTHONPATH = the folder an editable install exposes (accelerator/src of the worktree): tests start "
                 "`python -m ml_model_factory` as a subprocess, which does not see pytest's own pythonpath setting. "
                 "The `vision` extra (torch, torchvision, torchmetrics, pycocotools, Pillow) is not installed: the vision "
                 "tests skip through the repo's own importorskip('PIL.Image'). Installing Pillow alone would turn those "
                 "skips into failures ('Vision training requires the declared [train,vision] extras').",
        "repo_command": 'python -m pip install -e ".[train,azure,dev]"; python -m pytest  from 50-ml-model-factory (readme); '
                        "pytest config: testpaths=accelerator/tests, pythonpath=accelerator/src,accelerator",
    },
    {
        "id": "mlops-2026-09", "kind": "pytest", "component": MLOPS, "cwd": MF, "python": "3.12",
        "files": [(MLOPS + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [MF + "/pyproject.toml", MF + "/setup.cfg"],
        "install": MF_DEPS,
        "pythonpath": [MF + "/accelerator/src", MF + "/accelerator"],
        "test": ["{py}", "-m", "pytest", "../../" + MLOPS + "/tests"],
        "repo_command": r"model-factory .venv python: -m unittest discover -s <template>\tests -v (ado/github ml-factory.yml); "
                        "documentation/v2/30-39/36-dataops.md runs it with pytest from the model-factory root",
    },
    {
        "id": "dataops-adf", "kind": "pytest", "component": ADF, "cwd": MF, "python": "3.12",
        "files": [(ADF + "/tests", r"^test_[^/]*\.py$")],
        "inputs": [MF + "/pyproject.toml", MF + "/setup.cfg"],
        "install": MF_DEPS,
        "pythonpath": [MF + "/accelerator/src", MF + "/accelerator"],
        "test": ["{py}", "-m", "pytest", "../../" + ADF + "/tests"],
        "repo_command": r'python -m unittest discover -s "$templates\tests" -v (azure-datafactory/readme.md); '
                        "documentation/v2/30-39/36-dataops.md runs it with pytest from the model-factory root",
    },
    {
        "id": "onion", "kind": "pytest", "component": ONION, "cwd": ONION, "python": "3.12",
        "files": [(ONION, r"^test_[^/]*\.py$")],
        "inputs": [],
        "install": [{"name": "pytest (test is stdlib unittest)", "alternatives": [pip(PYTEST_PIN)]}],
        "test": ["{py}", "-m", "pytest", "test_onion.py"],
        "repo_command": "python -m unittest test_onion.py from the onion folder "
                        "(documentation/v2/10-19/10-factory-onion-architecture-v2.md)",
    },
    {
        "id": "tutorial-distribution-ps1", "kind": "pwsh", "component": TUTORIAL, "cwd": TUTORIAL,
        "files": [(TUTORIAL + "/tests", r"^Test-[^/]*\.ps1$")],
        "test": ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", "tests/Test-Distribution.ps1"],
        "windows_only": "Windows-only: Test-Distribution.ps1 drives scripts/Publish-TutorialApp.ps1, which requires "
                        "Windows path semantics ($OutputRoot.StartsWith($root + '\\'), regex '\\\\(artifacts|staging|private)'), "
                        "subst.exe, pwsh.exe and Authenticode. Tried on Linux with pwsh 7.4.6 (offline, no parameters): it "
                        "stops at the first Publish call with 'OutputRoot must be a child of this distribution directory'. "
                        "Needs Windows 11 + PowerShell 7.4 (and, for the optional parts, the ESAIF.TutorialApp source and "
                        "Inno Setup). --run-windows-only forces the attempt.",
        "repo_command": r".\tests\Test-Distribution.ps1 [-SourceRoot <ESAIF.TutorialApp source>] [-ExercisePackaging] "
                        "(README.packaging-draft.md); run without parameters: the app source is not in this repository",
    },
    {
        "id": "agent-foundry-legacy", "kind": "not-run", "component": "usecase_code/20-agent-foundry/_legacy",
        "files": [("usecase_code/20-agent-foundry/_legacy", r"^[^/]*_test\.py$")],
        "reason": "agent_01_rag_test.py is not a test: it has no test function or TestCase; it is a live sample script "
                  "(DefaultAzureCredential, creates an AI Search index and a Foundry agent). Needs Azure login and "
                  "deployed AI Foundry + AI Search; forbidden offline.",
    },
    {
        "id": "automl-scoring-file", "kind": "not-run",
        "component": "copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl",
        "files": [("copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl",
                   r"^[^/]*_test\.py$")],
        "reason": "scoring_file_test.py is not a test: it is an Azure AutoML scoring script (init()/run()) for the 'test' "
                  "environment, with no test function. It imports azureml.automl.core / inference_schema (Azure ML SDK v1 "
                  "AutoML runtime) and needs a registered model file.",
    },
]
SUITE_IDS = [s["id"] for s in SUITES]


# ---------------------------------------------------------------------------------------------
def utc():
    return dt.datetime.now(dt.timezone.utc)


def stamp(t=None):
    return (t or utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(worktree, *args):
    try:
        out = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True, timeout=120)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def tracked_files(worktree, folder):
    listed = git(worktree, "ls-files", "-z", "--", folder)
    if listed:
        return [p for p in listed.split("\0") if p]
    base = Path(worktree) / folder
    return [str(p.relative_to(worktree)).replace(os.sep, "/") for p in base.rglob("*") if p.is_file()]


def count_test_files(worktree, suite):
    total = 0
    for folder, pattern in suite.get("files", []):
        rx = re.compile(pattern)
        for path in tracked_files(worktree, folder):
            below = path[len(folder):].lstrip("/")
            if rx.search(below):
                total += 1
    return total


def status_snapshot(worktree):
    """Path -> XY code of `git status --porcelain --ignored` (untracked and ignored paths included)."""
    out = git(worktree, "status", "--porcelain", "--ignored", "-z")
    result = {}
    for entry in out.split("\0"):
        if len(entry) > 3:
            result[entry[3:]] = entry[:2]
    return result


def fill(value, mapping):
    if isinstance(value, list):
        return [fill(v, mapping) for v in value]
    for key, replacement in mapping.items():
        value = value.replace("{" + key + "}", str(replacement))
    return value


def python_for(version):
    for candidate in ("/usr/bin/python" + version, shutil.which("python" + version)):
        if candidate and Path(candidate).is_file():
            return candidate
    return version  # let uv resolve it


def venv_hash(worktree, suite):
    h = hashlib.sha256()
    h.update(RECIPE_VERSION.encode())
    h.update(suite.get("python", "").encode())
    h.update(json.dumps(suite.get("install", []), sort_keys=True, default=lambda f: f.__name__).encode())
    for rel in suite.get("inputs", []):
        path = Path(worktree) / rel
        h.update(rel.encode())
        h.update(path.read_bytes() if path.is_file() else b"<missing>")
    return h.hexdigest()


def run_logged(argv, log, env=None, cwd=None, timeout=1800):
    log.write("$ " + " ".join(argv) + "\n")
    log.flush()
    try:
        return subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=cwd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        log.write("\n[runner] install command timed out\n")
        return 124
    except OSError as error:
        log.write("\n[runner] cannot start: %s\n" % error)
        return 127


def ensure_venv(worktree, suite, venvs, outdir, skip_install):
    """Return (python, info). info: built/reused, recipe actually used, error."""
    venv = venvs / suite["id"]
    py = venv / "bin" / "python"
    stamp_file = venv / ".suite-stamp.json"
    wanted = venv_hash(worktree, suite)
    previous = {}
    if stamp_file.is_file():
        try:
            previous = json.loads(stamp_file.read_text())
        except ValueError:
            previous = {}
    info = {"venv": str(venv), "python_version": suite["python"], "inputs_sha256": wanted}
    if skip_install:
        if not py.is_file():
            info["error"] = "venv is missing and --skip-install was given"
        else:
            info.update(action="reused (--skip-install)", recipe=previous.get("recipe", []),
                        stale=previous.get("hash") != wanted)
        return py, info
    if py.is_file() and previous.get("hash") == wanted:
        info.update(action="reused (stamp matches)", recipe=previous.get("recipe", []))
        return py, info
    mapping = {"wt": worktree, "venv": venv, "py": py, "uv": UV}
    env = dict(os.environ, UV_PYTHON_PREFERENCE="only-system", UV_LINK_MODE="copy")
    started = time.time()
    recipe = []
    with open(outdir / "install.log", "w", encoding="utf-8") as log:
        code = run_logged([UV, "venv", "--clear", "--seed", "--python", python_for(suite["python"]), str(venv)], log, env)
        recipe.append("uv venv --seed --python %s %s" % (suite["python"], venv))
        if code != 0:
            info["error"] = "uv venv failed (exit %s), see install.log" % code
            return py, info
        for step in suite.get("install", []):
            used = None
            for number, alternative in enumerate(step["alternatives"], 1):
                log.write("\n## %s - alternative %d of %d\n" % (step["name"], number, len(step["alternatives"])))
                if callable(alternative):
                    log.write("# %s: %s\n" % (alternative.__name__, (alternative.__doc__ or "").strip().splitlines()[0]))
                    context = dict(mapping, venvs=venvs)
                    if alternative(context, log, env) == 0:
                        used = (number, ["%s()  # %s" % (alternative.__name__,
                                                         (alternative.__doc__ or "").strip().splitlines()[0])])
                        break
                    continue
                argv = fill(alternative, mapping)
                if run_logged(argv, log, env) == 0:
                    used = (number, argv)
                    break
            if used is None:
                info["error"] = "install step failed: %s (see install.log)" % step["name"]
                info["recipe"] = recipe
                return py, info
            shown = " ".join(used[1])
            shown = shown.replace(str(worktree), "<worktree>").replace(str(py), "<venv>/bin/python").replace(UV, "uv")
            fallback = "" if used[0] == 1 else "  [FALLBACK: alternative %d; earlier alternatives failed]" % used[0]
            recipe.append(shown + fallback)
        freeze = subprocess.run([UV, "pip", "freeze", "--python", str(py)], capture_output=True, text=True, env=env)
        (venv / "pip-freeze.txt").write_text(freeze.stdout, encoding="utf-8")
    stamp_file.write_text(json.dumps({"hash": wanted, "recipe": recipe, "python": suite["python"],
                                      "built_utc": stamp(), "built_from": str(worktree)}, indent=1), encoding="utf-8")
    info.update(action="built", recipe=recipe, install_seconds=round(time.time() - started, 1))
    return py, info


def test_env(worktree, suite, venv, py):
    """--no-wrapper only: the inherited environment (proxy variables and injected tokens included) plus tools."""
    env = dict(os.environ)
    for name in ("AIF_TEST_TIERS", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTEST_ADDOPTS"):
        env.pop(name, None)
    path = list(TOOL_DIRS)
    if py is not None:
        path.insert(0, str(Path(py).parent))
        env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = os.pathsep.join(path + [env.get("PATH", "")])
    env.update(PYTHONDONTWRITEBYTECODE="1", LIVE_AZURE="0", PYTHONUTF8="1", COLUMNS="200", NO_COLOR="1")
    env.update(suite_variables(worktree, suite, venv))
    return env


def suite_variables(worktree, suite, venv):
    """Variables a suite needs on top of the CI environment (code under test from the worktree, caches)."""
    extra = {}
    if suite.get("pythonpath"):
        extra["PYTHONPATH"] = os.pathsep.join(str(Path(worktree) / p) for p in suite["pythonpath"])
    for key, value in suite.get("env", {}).items():
        extra[key] = fill(value, {"wt": worktree, "venv": venv, "venvs": Path(venv).parent if venv else ""})
    return extra


def wrap(argv, worktree, suite, venv, py):
    """argv wrapped in the CI wrapper, the suite variables and the effective environment of the command."""
    extra = suite_variables(worktree, suite, venv)
    prefix = [CI_WRAPPER] + ([str(Path(py).parent)] if py is not None else []) + ["--"]
    inner = (["env"] + ["%s=%s" % kv for kv in sorted(extra.items())]) if extra else []
    probe = subprocess.run(prefix + inner + ["env"], capture_output=True, text=True, timeout=60)
    effective = dict(line.split("=", 1) for line in probe.stdout.splitlines() if "=" in line)
    return prefix + inner + argv, extra, effective


def env_delta(env):
    """What the test command got on top of the base environment of the runner."""
    return {"set": {k: v for k, v in sorted(env.items()) if os.environ.get(k) != v},
            "removed": sorted(k for k in os.environ if k not in env)}


def run_test(argv, cwd, env, log_path, timeout):
    started = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write("$ (cwd=%s) %s\n" % (cwd, " ".join(argv)))
        log.flush()
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            log.write("[runner] cannot start: %s\n" % error)
            return 127, round(time.time() - started, 1), False
        try:
            code = process.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    process.wait(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    continue
            code = 124
            log.write("\n[runner] TIMEOUT after %s s; process group killed\n" % timeout)
    return code, round(time.time() - started, 1), timed_out


def parse_junit(path):
    counts = {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    failing, skipped = [], []
    if not Path(path).is_file():
        return None, failing, skipped
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None, failing, skipped
    for case in root.iter("testcase"):
        counts["tests"] += 1
        name = case.get("name", "")
        classname = case.get("classname", "")
        ident = (classname + "::" + name) if classname else name
        children = {child.tag: child for child in case}
        if "failure" in children or "error" in children:
            kind = "failure" if "failure" in children else "error"
            counts["failed" if kind == "failure" else "errors"] += 1
            node = children[kind]
            text = (node.get("message") or node.text or "").strip().splitlines()
            failing.append({"id": ident, "kind": kind, "reason": (text[0] if text else "")[:300]})
        elif "skipped" in children:
            counts["skipped"] += 1
            node = children["skipped"]
            skipped.append({"id": ident, "reason": (node.get("message") or "").strip()[:200]})
        else:
            counts["passed"] += 1
    return counts, failing, skipped


SUMMARY_RX = re.compile(r"\b\d+ (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b|no tests ran")
SHORT_RX = re.compile(r"^(FAILED|ERROR|SUBFAILED(?:\([^)]*\))?) (.+?)(?: - (.*))?$")


def parse_pytest_log(path):
    last, failing = "", []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return last, failing
    for line in lines:
        clean = line.strip().strip("=").strip()
        if SUMMARY_RX.search(clean) and " in " in clean:
            last = clean
        match = SHORT_RX.match(line.strip())
        if match and not any(item["id"] == match.group(2) for item in failing):
            kind = {"FAILED": "failure", "ERROR": "error"}.get(match.group(1), "sub-test failure")
            failing.append({"id": match.group(2), "kind": kind, "reason": (match.group(3) or "")[:300]})
    return last, failing


def write_single_junit(path, suite_id, name, seconds, failure=None, properties=None):
    props = "".join('<property name="%s" value="%s"/>' % (escape(k), escape(str(v)).replace('"', "&quot;"))
                    for k, v in (properties or {}).items())
    body = "" if failure is None else '<failure message="%s"></failure>' % escape(failure[:500]).replace('"', "&quot;")
    Path(path).write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite name="%s" tests="1" failures="%d" errors="0" '
        'skipped="0" time="%.1f"><properties>%s</properties><testcase classname="%s" name="%s" time="%.1f">%s</testcase>'
        "</testsuite></testsuites>\n" % (escape(suite_id), 0 if failure is None else 1, seconds, props,
                                         escape(suite_id), escape(name), seconds, body), encoding="utf-8")


def run_suite(suite, worktree, results, venvs, args):
    outdir = results / suite["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    entry = {"id": suite["id"], "component": suite["component"], "kind": suite["kind"],
             "cwd": suite.get("cwd", ""), "test_files": count_test_files(worktree, suite),
             "tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "seconds": 0.0,
             "exit_code": None, "status": "not-run", "failing": [], "summary_line": "",
             "repo_command": suite.get("repo_command", ""), "notes": suite.get("notes", "")}
    if suite["kind"] == "not-run":
        entry["reason"] = suite["reason"]
        return entry
    if suite.get("windows_only") and os.name != "nt" and not args.run_windows_only:
        entry["reason"] = suite["windows_only"]
        return entry
    cwd = Path(worktree) / suite["cwd"]
    if not cwd.is_dir():
        entry["reason"] = "component folder is missing in this worktree: %s" % suite["cwd"]
        return entry
    junit = outdir / "junit.xml"
    log_path = outdir / "pytest.log"
    for stale in (junit, log_path):
        if stale.exists():
            stale.unlink()
    venv = py = None
    if suite["kind"] == "pytest":
        venv = venvs / suite["id"]
        py, info = ensure_venv(worktree, suite, venvs, outdir, args.skip_install)
        entry["environment"] = info
        if (venv / "pip-freeze.txt").is_file():
            shutil.copyfile(venv / "pip-freeze.txt", outdir / "pip-freeze.txt")
        if info.get("error"):
            entry["reason"] = info["error"]
            return entry
        if args.install_only:
            entry["reason"] = "--install-only"
            return entry
    elif args.install_only:
        entry["reason"] = "--install-only"
        return entry
    env = test_env(worktree, suite, venv, py)
    mapping = {"wt": worktree, "venv": venv, "py": py, "uv": UV}
    argv = fill(suite.get("test", []), mapping)
    if suite["kind"] == "pytest":
        argv += ([] if suite.get("quiet_in_config") else ["-q"]) + PYTEST_FLAGS + ["--junitxml=" + str(junit)]
    elif suite["kind"] == "node":
        node = shutil.which("node", path=env["PATH"])
        files = sorted(glob.glob(str(cwd / suite["glob"])))
        if not node or not files:
            entry["reason"] = "node not found" if not node else "no file matches " + suite["glob"]
            return entry
        argv = [node, "--test", "--test-reporter=spec", "--test-reporter-destination=stdout",
                "--test-reporter=junit", "--test-reporter-destination=" + str(junit)] + \
               [os.path.relpath(f, cwd) for f in files]
    elif suite["kind"] == "pwsh":
        tool = shutil.which(argv[0], path=env["PATH"])
        if not tool:
            entry["reason"] = "pwsh not found on PATH"
            return entry
        argv[0] = tool
    if args.no_wrapper:
        entry["environment_mode"] = "built-in (no wrapper)"
        entry["env_delta"] = env_delta(env)
        entry["suite_variables"] = suite_variables(worktree, suite, venv)
    else:
        if not os.access(CI_WRAPPER, os.X_OK):
            entry["reason"] = "CI wrapper %s is missing or not executable (use --no-wrapper to run without it)" % CI_WRAPPER
            return entry
        argv, extra, effective = wrap(argv, worktree, suite, venv, py)
        entry["environment_mode"] = "wrapper"
        entry["wrapper"] = {"path": CI_WRAPPER, "sha256": hashlib.sha256(Path(CI_WRAPPER).read_bytes()).hexdigest()}
        entry["suite_variables"] = extra            # passed as `env VAR=value` inside the wrapped command
        entry["effective_environment"] = effective  # complete environment of the test command (env -i based)
        env = dict(os.environ)                      # irrelevant: the wrapper starts from an empty environment
    entry["command"] = " ".join(argv).replace(str(worktree), "<worktree>")
    before = status_snapshot(worktree)
    entry["started_utc"] = stamp()
    code, seconds, timed_out = run_test(argv, str(cwd), env, log_path, suite.get("timeout", args.timeout))
    entry["finished_utc"] = stamp()
    entry["exit_code"], entry["seconds"] = code, seconds
    after = status_snapshot(worktree)
    fresh = sorted(p for p in after if p not in before and not p.startswith("environment_setup/unit-tests/test-bicep/"))
    # The test process runs with PYTHONDONTWRITEBYTECODE=1, so new __pycache__ folders normally come from another
    # job that uses the same worktree at the same time; they are listed separately and never removed.
    created = [p for p in fresh if "__pycache__" not in p]
    entry["worktree_new_paths"] = [after[p].strip() + " " + p for p in created]
    entry["worktree_new_pycache"] = [p for p in fresh if "__pycache__" in p]
    if created and args.clean_created:
        owned = [suite["component"].rstrip("/") + "/", suite["cwd"].rstrip("/") + "/"]
        removed = []
        for path in created:
            target = Path(worktree) / path
            if after[path] in ("??", "!!") and any(path.startswith(o) for o in owned) and "__pycache__" not in path:
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists() or target.is_symlink():
                    target.unlink()
                removed.append(path)
        entry["worktree_removed"] = removed

    if suite["kind"] == "pwsh":
        text = log_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"PASS: (\d+) checks", text)
        failure = None
        if code != 0 or not match:
            lines = [l for l in text.splitlines()[1:] if l.strip() and not l.startswith("[runner]")]
            failure = (lines[0] if lines else "exit code %s" % code)[:300]
        write_single_junit(junit, suite["id"], "Test-Distribution.ps1", seconds, failure,
                           {"checks": match.group(1) if match else "unknown"})
        entry["summary_line"] = match.group(0) if match else "no PASS line"
        if match:
            entry["checks"] = int(match.group(1))
    counts, failing, skipped = parse_junit(junit)
    last, short = parse_pytest_log(log_path) if suite["kind"] == "pytest" else (entry["summary_line"], [])
    entry["summary_line"] = last or entry["summary_line"]
    if suite["kind"] == "node":
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail = [l.strip() for l in text.splitlines() if re.match(r"^\S* ?(tests|pass|fail|skipped|cancelled|todo) \d+", l.strip())]
        entry["summary_line"] = ", ".join(t.lstrip("ℹ# ").strip() for t in tail)
    if counts:
        entry.update(counts)
    if short:
        full = {item["id"]: item["reason"] for item in failing}
        for item in short:
            path, _, rest = item["id"].partition("::")
            parts = rest.split("::") if rest else []
            module = re.sub(r"\.py$", "", path).replace("/", ".")
            key = ".".join([module] + parts[:-1]) + "::" + (parts[-1] if parts else "")
            if full.get(key):
                item["reason"] = full[key]
    entry["failing"] = short or failing
    entry["skipped_reasons"] = sorted({s["reason"] for s in skipped})[:40]
    if timed_out:
        entry["status"] = "timeout"
        entry["reason"] = "killed after %s s" % suite.get("timeout", args.timeout)
    elif counts is None:
        entry["status"] = "fail"
        entry["reason"] = "no junit.xml was produced (exit code %s); see pytest.log" % code
    elif code == 0 and entry["failed"] == 0 and entry["errors"] == 0 and entry["tests"] > 0:
        entry["status"] = "pass"
    else:
        entry["status"] = "fail"
        if entry["tests"] == 0:
            entry["reason"] = "no test was collected (exit code %s)" % code
    return entry


def rerun_failing(worktree, results, venvs, args, only):
    """Run every failing test id of summary.json once more, alone, to tell flaky from reproducible."""
    summary_path = results / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    suites = {s["id"]: s for s in SUITES}
    for entry in summary["suites"]:
        suite = suites.get(entry["id"])
        if not suite or suite["kind"] != "pytest" or not entry.get("failing") or (only and entry["id"] not in only):
            continue
        venv = venvs / suite["id"]
        py = venv / "bin" / "python"
        cwd = Path(worktree) / suite["cwd"]
        env = test_env(worktree, suite, venv, py)
        outdir = results / suite["id"] / "rerun"
        shutil.rmtree(outdir, ignore_errors=True)
        outdir.mkdir(parents=True)
        outcomes = []
        for number, item in enumerate(entry["failing"][:args.rerun_limit], 1):
            path, _, rest = item["id"].partition("::")
            target = next((base / path for base in (cwd, Path(worktree), Path(worktree) / suite["component"])
                           if (base / path).exists()), cwd / path)
            node = str(target) + (("::" + rest) if rest else "")
            argv = [str(py), "-m", "pytest", node] + ([] if suite.get("quiet_in_config") else ["-q"]) + PYTEST_FLAGS
            if not args.no_wrapper:
                argv = wrap(argv, worktree, suite, venv, py)[0]
            code, seconds, timed_out = run_test(argv, str(cwd), env, outdir / ("%03d.log" % number), 600)
            last, _ = parse_pytest_log(outdir / ("%03d.log" % number))
            outcome = "timeout" if timed_out else "passed" if code == 0 else "failed-again"
            outcomes.append({"id": item["id"], "outcome": outcome, "exit_code": code, "seconds": seconds, "summary_line": last})
            print("[rerun] %-28s %-12s %s" % (entry["id"], outcome, item["id"][:150]), flush=True)
        entry["rerun"] = outcomes
        entry["rerun_verdict"] = {"reproducible": sum(o["outcome"] == "failed-again" for o in outcomes),
                                  "flaky_or_order_dependent": [o["id"] for o in outcomes if o["outcome"] == "passed"],
                                  "not_rerun": max(0, len(entry["failing"]) - args.rerun_limit)}
    summary["porcelain_after"] = git(worktree, "status", "--porcelain").strip()
    summary_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (results / "summary.md").write_text(markdown(summary), encoding="utf-8")
    return 0


def markdown(summary):
    lines = ["# Component suites - %s" % summary["worktree"], "",
             "HEAD `%s`, run %s .. %s, runner recipe %s." % (summary.get("head", "?"), summary.get("started_utc", "?"),
                                                              summary.get("finished_utc", "?"), RECIPE_VERSION), "",
             "| suite | test files | tests | passed | failed | errors | skipped | seconds | exit | status |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for e in summary["suites"]:
        lines.append("| %s | %d | %d | %d | %d | %d | %d | %.1f | %s | %s |" % (
            e["id"], e["test_files"], e["tests"], e["passed"], e["failed"], e["errors"], e["skipped"],
            e["seconds"], "" if e["exit_code"] is None else e["exit_code"], e["status"]))
    totals = {k: sum(e[k] for e in summary["suites"]) for k in ("test_files", "tests", "passed", "failed", "errors", "skipped", "seconds")}
    lines.append("| **total** | %d | %d | %d | %d | %d | %d | %.1f | | |" % (
        totals["test_files"], totals["tests"], totals["passed"], totals["failed"], totals["errors"],
        totals["skipped"], totals["seconds"]))
    lines += ["", "## Failing, timed-out and not-run suites", ""]
    for e in summary["suites"]:
        if e["status"] == "pass":
            continue
        lines.append("### %s - %s" % (e["id"], e["status"]))
        if e.get("reason"):
            lines.append("Reason: %s" % e["reason"])
        if e.get("summary_line"):
            lines.append("Last pytest line: `%s`" % e["summary_line"])
        again = {o["id"]: o["outcome"] for o in e.get("rerun", [])}
        for item in e.get("failing", []):
            lines.append("- `%s` (%s): %s%s" % (item["id"], item["kind"], item["reason"],
                                                 (" [alone: %s]" % again[item["id"]]) if item["id"] in again else ""))
        if e.get("rerun_verdict"):
            verdict = e["rerun_verdict"]
            lines.append("- Isolated re-run: %d reproducible, %d passed alone (flaky or order dependent)%s" % (
                verdict["reproducible"], len(verdict["flaky_or_order_dependent"]),
                (", %d not re-run" % verdict["not_rerun"]) if verdict["not_rerun"] else ""))
        lines.append("")
    lines += ["## Commands and environments", ""]
    for e in summary["suites"]:
        lines.append("### %s (`%s`)" % (e["id"], e["component"]))
        if e.get("repo_command"):
            lines.append("- Repo's own command: %s" % e["repo_command"])
        if e.get("command"):
            lines.append("- Executed (cwd `<worktree>/%s`): `%s`" % (e["cwd"], e["command"]))
        if e.get("environment_mode") == "wrapper":
            lines.append("- Test environment: `%s <venv bin> --` (env -i, CI-like); suite variables passed inside: `%s`" % (
                e["wrapper"]["path"], " ".join("%s=%s" % kv for kv in sorted(e.get("suite_variables", {}).items())) or "none"))
        delta = e.get("env_delta")
        if delta:
            lines.append("- Environment on top of the base environment: set `%s`; removed `%s`" % (
                " ".join("%s=%s" % kv for kv in sorted(delta["set"].items())), " ".join(delta["removed"]) or "-"))
        elif e.get("env"):
            lines.append("- Environment: `%s`" % " ".join("%s=%s" % kv for kv in sorted(e["env"].items())))
        environment = e.get("environment") or {}
        if environment:
            lines.append("- venv `%s`, Python %s, %s" % (environment.get("venv"), environment.get("python_version"),
                                                           environment.get("action", environment.get("error", ""))))
            for step in environment.get("recipe", []):
                lines.append("  - `%s`" % step)
        if e.get("summary_line"):
            lines.append("- Last summary line: `%s`" % e["summary_line"])
        if e.get("skipped_reasons"):
            lines.append("- Skip reasons: " + "; ".join(e["skipped_reasons"]))
        if e.get("worktree_new_paths"):
            lines.append("- New paths in the worktree after the run: " + ", ".join("`%s`" % p for p in e["worktree_new_paths"]))
        if e.get("worktree_removed"):
            lines.append("- Removed afterwards (--clean-created): " + ", ".join("`%s`" % p for p in e["worktree_removed"]))
        if e.get("notes"):
            lines.append("- Note: %s" % e["notes"])
        lines.append("")
    lines.append("`git status --porcelain` after the run: %s" % ("empty" if not summary.get("porcelain_after") else
                                                                 "`%s`" % summary["porcelain_after"]))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worktree")
    parser.add_argument("--results")
    parser.add_argument("--only", default="", help="comma separated suite ids")
    parser.add_argument("--skip-install", action="store_true", help="never create or change a venv")
    parser.add_argument("--install-only", action="store_true", help="build the venvs, run no test")
    parser.add_argument("--venvs", default=str(DEFAULT_VENVS))
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--clean-created", action="store_true",
                        help="remove new untracked/ignored paths a suite left under its own component folder")
    parser.add_argument("--run-windows-only", action="store_true",
                        help="also attempt suites that are marked Windows-only (they write tests/.work-* and remove it)")
    parser.add_argument("--rerun-failing", action="store_true",
                        help="re-run each failing test id of <results>/summary.json once, alone (flaky or reproducible?)")
    parser.add_argument("--rerun-limit", type=int, default=80, help="maximum ids re-run per suite")
    parser.add_argument("--no-wrapper", action="store_true",
                        help="do not wrap the test command in the CI wrapper (%s); run it in the inherited environment "
                             "(proxy variables and injected tokens kept) with the tool folders on PATH" % CI_WRAPPER)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for suite in SUITES:
            print("%-34s %-8s %s" % (suite["id"], suite["kind"], suite["component"]))
        return 0
    if not args.worktree or not args.results:
        parser.error("--worktree and --results are required")
    worktree = Path(args.worktree).resolve()
    results = Path(args.results).resolve()
    venvs = Path(args.venvs).resolve()
    if not worktree.is_dir():
        parser.error("worktree does not exist: %s" % worktree)
    try:
        results.relative_to(worktree)
        parser.error("--results must be outside the worktree")
    except ValueError:
        pass
    only = [s for s in args.only.split(",") if s]
    unknown = [s for s in only if s not in SUITE_IDS]
    if unknown:
        parser.error("unknown suite id(s): %s (known: %s)" % (", ".join(unknown), ", ".join(SUITE_IDS)))
    results.mkdir(parents=True, exist_ok=True)
    venvs.mkdir(parents=True, exist_ok=True)
    summary_path = results / "summary.json"
    existing = {}
    if summary_path.is_file() and not args.install_only:
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if loaded.get("worktree") == str(worktree):
                existing = {e["id"]: e for e in loaded.get("suites", [])}
        except ValueError:
            existing = {}
    if args.rerun_failing:
        return rerun_failing(worktree, results, venvs, args, only)
    started = utc()
    done = {}
    for suite in SUITES:
        if only and suite["id"] not in only:
            continue
        print("[%s] %-34s ..." % (utc().strftime("%H:%M:%S"), suite["id"]), end=" ", flush=True)
        entry = run_suite(suite, worktree, results, venvs, args)
        done[suite["id"]] = entry
        print("%s  tests=%d passed=%d failed=%d errors=%d skipped=%d  %.1fs  %s" % (
            entry["status"], entry["tests"], entry["passed"], entry["failed"], entry["errors"], entry["skipped"],
            entry["seconds"], entry.get("reason", "") or entry.get("summary_line", "")), flush=True)
    if args.install_only:
        return 0 if all(not (e.get("environment") or {}).get("error") for e in done.values()) else 1
    merged = [done.get(sid) or existing.get(sid) for sid in SUITE_IDS]
    summary = {"worktree": str(worktree), "head": git(worktree, "rev-parse", "HEAD").strip(),
               "started_utc": stamp(started), "finished_utc": stamp(), "runner_recipe": RECIPE_VERSION,
               "ran_this_invocation": list(done), "porcelain_after": git(worktree, "status", "--porcelain").strip(),
               "suites": [e for e in merged if e]}
    summary_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (results / "summary.md").write_text(markdown(summary), encoding="utf-8")
    print("summary: %s and %s" % (summary_path, results / "summary.md"))
    bad = [e["id"] for e in done.values() if e["status"] in ("fail", "timeout")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
