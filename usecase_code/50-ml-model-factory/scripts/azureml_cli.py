"""CLI v2 submission of the identical rendered job; registration stays gated."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text(encoding="utf-8-sig"))
    if "REPLACE_WITH_" in args.job.read_text(encoding="utf-8"):
        raise ValueError("Resolve job input placeholders before CLI submission")
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Install Azure CLI and its ml v2 extension, then sign in to runtime.tenant_id")
    subprocess.run([
        executable, "ml", "job", "create", "--file", str(args.job.resolve()),
        "--subscription", runtime["subscription_id"], "--resource-group", runtime["resource_group"],
        "--workspace-name", runtime["workspace_name"], "--query", "name", "--output", "tsv",
    ], check=True)


if __name__ == "__main__":
    main()
