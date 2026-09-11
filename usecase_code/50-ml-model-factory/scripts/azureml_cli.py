"""CLI v2 submission of the identical rendered job; registration stays gated."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--job", type=Path)
    action.add_argument("--register-job", help="Completed evaluated pipeline whose model is to be registered")
    parser.add_argument("--model-name")
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text(encoding="utf-8-sig"))
    if args.register_job:
        if not args.model_name:
            raise ValueError("--model-name is required with --register-job")
        from ml_model_factory.azureml import registration_definition
        from ml_model_factory.project import azure_cli
        definition = registration_definition(args.register_job, runtime, args.model_name)
        with tempfile.TemporaryDirectory(prefix="factory-model-registration-") as temporary:
            path = Path(temporary) / "model.yml"
            path.write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")
            model = azure_cli("ml", "model", "create", "--file", str(path),
                              "--subscription", runtime["subscription_id"],
                              "--resource-group", runtime["resource_group"],
                              "--workspace-name", runtime["workspace_name"])
        print(model["id"])
        return
    if "REPLACE_WITH_" in args.job.read_text(encoding="utf-8"):
        raise ValueError("Resolve job input placeholders before CLI submission")
    from ml_model_factory.tags import assert_scope
    definition = yaml.safe_load(args.job.read_text(encoding="utf-8"))
    assert_scope(definition.get("tags", {}), runtime)
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
