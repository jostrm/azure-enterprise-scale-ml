#!/usr/bin/env python3
"""Launcher for pipelines and local use without installing the package.

    python azure-enterprise-scale-ml/healthmodel/aif_healthmodel.py plan --variables-json aifactory/variables.json --environment dev --project 001
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from aifactory_healthmodel.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
