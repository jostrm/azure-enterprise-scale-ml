"""Collect redistributable dependency notices from the actual build environment."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET


def copy_notice(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def notice(path):
    return bool(re.search(r"license|licence|copying|copyright|third.party|notice", path.name, re.I))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--accelerator", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for source in (args.root / "installer" / "licenses").glob("*.txt"):
        copy_notice(source, args.output / source.name)
    inventory = []
    for dist in importlib.metadata.distributions():
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", dist.metadata["Name"])
        files = []
        for file in dist.files or []:
            source = Path(dist.locate_file(file))
            if source.is_file() and (notice(source) or "licenses" in source.parts):
                target = args.output / "Python" / name / Path(*file.parts[-3:])
                copy_notice(source, target)
                files.append(str(target.relative_to(args.output)))
        inventory.append({"ecosystem": "Python build environment", "name": name, "version": dist.version,
                          "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                          "notices": files})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python runtime license missing")
    copy_notice(python_license, args.output / "Python" / "Python-LICENSE.txt")
    for subtree in ("tcl", "DLLs"):
        for source in (Path(sys.base_prefix) / subtree).rglob("*"):
            if source.is_file() and notice(source):
                copy_notice(source, args.output / "Python" / source.relative_to(sys.base_prefix))
    assets = json.loads((args.root / "src" / "ESAIF.ConfigWizard" / "obj" / "project.assets.json").read_text())
    package_roots = [Path(path) for path in assets["packageFolders"]]
    packages = set()
    for target, libraries in assets["targets"].items():
        if "windows" in target.lower():
            packages.update(libraries)
    deps = json.loads((args.publish / "ESAIF.ConfigWizard.deps.json").read_text())
    for library in deps["libraries"]:
        if library.startswith("runtimepack."):
            name = library.removeprefix("runtimepack.")
            assets["libraries"][name] = {"type": "package", "path": name.lower()}
            packages.add(name)
    for library in sorted(packages):
        record = assets["libraries"][library]
        if record.get("type") != "package":
            continue
        package = next((root / record["path"] for root in package_roots if (root / record["path"]).is_dir()), None)
        if package is None:
            raise RuntimeError(f"NuGet package missing: {library}")
        files = []
        for file in package.rglob("*"):
            if file.is_file() and notice(file):
                target = args.output / "NuGet" / record["path"] / file.relative_to(package)
                copy_notice(file, target)
                files.append(str(target.relative_to(args.output)))
        nuspec = next(package.glob("*.nuspec"), None)
        license_text = None
        if nuspec:
            tree = ET.parse(nuspec)
            values = [element.text for element in tree.iter() if element.tag.split("}")[-1] in ("license", "licenseUrl")]
            license_text = "; ".join(value for value in values if value)
            copy_notice(nuspec, args.output / "NuGet" / record["path"] / nuspec.name)
        inventory.append({"ecosystem": "NuGet", "name": library, "license": license_text, "notices": files})
    for source in args.accelerator.glob("*"):
        if source.is_file() and notice(source):
            copy_notice(source, args.output / "Accelerator" / source.name)
    inno = args.root / "artifacts" / "installer-tools" / "InnoSetup" / "license.txt"
    if inno.is_file():
        copy_notice(inno, args.output / "InnoSetup-LICENSE.txt")
    (args.output / "dependency-inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
