"""terraform validate of the root module (and with it every module it reaches)."""
from harness import terraform


def test_root_module_validates(terraform_copy, tmp_path):
    result = terraform("validate", "-no-color", cwd=terraform_copy["root"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_root_module_initialises_without_a_backend_and_validates(tmp_path):
    """The repository configuration itself: `init -backend=false` + `validate`, as the task requires."""
    from harness import copy_terraform_tree

    root = copy_terraform_tree(tmp_path / "terraform")
    result = terraform("init", "-backend=false", "-input=false", "-no-color", cwd=root, timeout=1800)
    assert result.returncode == 0, result.stdout + result.stderr
    result = terraform("validate", "-no-color", cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stage_wrapper_validates(terraform_copy):
    result = terraform("validate", "-no-color", cwd=terraform_copy["wrapper"])
    assert result.returncode == 0, result.stdout + result.stderr
