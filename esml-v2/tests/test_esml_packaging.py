import ast
from pathlib import Path
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_distribution_identity_and_v2_only_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "azure-esml-sdk"
    assert project["scripts"]["esml"] == "azure_esml.cli:main"
    dependencies = project["dependencies"] + [
        dependency for extra in project["optional-dependencies"].values() for dependency in extra
    ]
    assert any(dependency.startswith("azure-ai-ml") for dependency in dependencies)
    assert not any(dependency.startswith(("azureml-", "esmlrt", "esmlfac")) for dependency in dependencies)


def test_base_layer_does_not_depend_on_domain_or_customer_code():
    forbidden = ("azure_esml.domain_layer", "ml_model_factory", "esml.", "esmlrt", "esmlfac")
    for path in (ROOT / "azure_esml" / "base_layer").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(name.startswith(forbidden) for name in imports), path


def test_no_sdk_v1_imports_or_shared_class_mutable_state():
    for path in (ROOT / "azure_esml").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith(("azureml.", "esmlrt", "esmlfac")) for alias in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("azureml.", "esmlrt", "esmlfac")), path
            if isinstance(node, ast.ClassDef):
                for statement in node.body:
                    if isinstance(statement, ast.Assign):
                        assert not isinstance(statement.value, (ast.Dict, ast.List, ast.Set)), (path, node.name)


def test_build_stages_shared_engines_without_changing_cwd_or_maintaining_duplicates():
    import esml_build
    previous = Path.cwd()
    with esml_build._source():
        staging = Path.cwd()
        assert staging != previous
        assert (staging / "azure_esml" / "__init__.py").is_file()
        assert (staging / "ml_model_factory" / "selection.py").is_file()
        assert (staging / "LICENSE").is_file()
        assert not list(staging.rglob("*.pyc"))
    assert Path.cwd() == previous
    assert not staging.exists()
