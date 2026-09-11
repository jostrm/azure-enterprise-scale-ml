"""Manual administrator provisioning only; CI never invokes this installer."""
import argparse
import re
import shutil
import subprocess
import venv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--venv", required=True)
    parser.add_argument("--azure", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--kaggle", action="store_true")
    parser.add_argument("--ml-extension-version", choices=("2.38.1",))
    args = parser.parse_args()
    package = Path(args.package).resolve()
    if not (package / "pyproject.toml").is_file():
        parser.error("--package must point at usecase_code/50-ml-model-factory (or its copied location)")
    environment = Path(args.venv).resolve()
    if args.ml_extension_version and not re.fullmatch(r"\d+\.\d+\.\d+", args.ml_extension_version):
        parser.error("An exact ml extension version is required")
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
    extras = ["dev"]
    extras += ["azure"] if args.azure else []
    extras += ["train"] if args.train else []
    extras += ["kaggle"] if args.kaggle else []
    subprocess.run([str(python), "-m", "pip", "install", "--editable",
                    f"{package}[{','.join(extras)}]"], check=True)
    if args.ml_extension_version:
        az = shutil.which("az")
        if not az:
            raise RuntimeError("Preinstall Azure CLI on the self-hosted runner")
        subprocess.run([az, "config", "set", "extension.use_dynamic_install=no"], check=True)
        subprocess.run([az, "extension", "add", "--name", "ml", "--version",
                        args.ml_extension_version, "--upgrade", "--yes"], check=True)
        installed = subprocess.check_output(
            [az, "extension", "show", "--name", "ml", "--query", "version", "-o", "tsv"], text=True,
        ).strip()
        if installed != args.ml_extension_version:
            raise RuntimeError(f"Expected ml {args.ml_extension_version}, found {installed}")
    print(python)


if __name__ == "__main__":
    main()
