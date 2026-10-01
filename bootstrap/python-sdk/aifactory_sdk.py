"""Copyable Python SDK starter: prepare configuration, then explicitly approve a separate confirm."""

import argparse
import importlib
import importlib.util
from pathlib import Path
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, help="Edited request JSON; prepare only.")
    parser.add_argument("--receipt", type=Path, required=True, help="New prepare receipt or reviewed confirm receipt.")
    parser.add_argument("--confirm", action="store_true", help="Save only the separately approved configuration.")
    parser.add_argument("--yes", action="store_true", help="Explicit approval; required only for confirm.")
    parser.parse_args(argv)

    examples = (
        Path(__file__).resolve().parent / "azure-enterprise-scale-ml"
        / "environment_setup" / "install_config_wizard" / "api-usage-examples" / "python"
    )
    for name in ("create_factory.py", "inspect_factory.py"):
        if not (examples / name).is_file():
            print(
                f"Missing submodule support file: {examples / name}. "
                "Copy this starter to your consumer repo root and keep the initialized "
                "azure-enterprise-scale-ml submodule there.",
                file=sys.stderr,
            )
            return 2
    try:
        importlib.import_module("azurefactory")
    except ModuleNotFoundError as error:
        if error.name != "azurefactory":
            raise
        print(
            "Missing Python SDK. Install it in the Python environment running this starter: "
            r"python -m pip install -e .\azure-enterprise-scale-ml\environment_setup\azurefactory-cli",
            file=sys.stderr,
        )
        return 2

    original_path = sys.path[:]
    try:
        # create_factory imports its sibling inspect_factory; never copy that support file.
        sys.path.insert(0, str(examples))
        spec = importlib.util.spec_from_file_location("aifactory_create_example", examples / "create_factory.py")
        example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
    finally:
        sys.path[:] = original_path
    return example.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
