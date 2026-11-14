#!/usr/bin/env python3
"""Run the Terraform port suite in CI (GitHub Actions and locally): every tier, JUnit results, no Azure.

Usage: python run_ci.py [--terraform PATH] [--bicep PATH] [--results-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SUITE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--terraform", default=os.environ.get("TERRAFORM") or shutil.which("terraform"))
    parser.add_argument("--bicep", default=os.environ.get("BICEP") or shutil.which("bicep"))
    parser.add_argument("--results-dir", type=Path, default=SUITE / "test-results")
    args = parser.parse_args(argv)
    missing = [name for name, path in (("terraform", args.terraform), ("bicep", args.bicep)) if not path]
    if missing:
        print(f"Required tools are missing: {', '.join(missing)}", file=sys.stderr)
        return 1
    results = args.results_dir.resolve()
    results.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, TERRAFORM=args.terraform, BICEP=args.bicep, PYTHONUTF8="1", LIVE_AZURE="0",
                       CHECKPOINT_DISABLE="1")
    environment.pop("AIF_TEST_TIERS", None)  # the test-bicep tier selection does not apply here
    with tempfile.TemporaryDirectory(prefix="aifactory-tf-ci-") as temporary:
        environment["TMPDIR"] = Path(temporary).as_posix()
        code = subprocess.run([sys.executable, "-m", "pytest", "--tiers", "all", "-q", "--tb=short",
                               f"--junitxml={results / 'terraform-tests.xml'}"],
                              cwd=SUITE, env=environment, timeout=3600, check=False).returncode
    (results / "terraform-summary.json").write_text(json.dumps(
        {"failed": bool(code), "azure_deployment_performed": False}, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
