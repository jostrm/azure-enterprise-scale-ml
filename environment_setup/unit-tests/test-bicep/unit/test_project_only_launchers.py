"""Offline contract tests for project-only update launchers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
LAUNCHERS = [
    ROOT / "bootstrap" / "ADO-update-aifactory-and-run-project.sh",
    ROOT / "bootstrap" / "GH-update-aifactory-and-run-project.sh",
]


def test_project_only_flag_skips_update_and_publish_operations() -> None:
    for launcher in LAUNCHERS:
        source = launcher.read_text(encoding="utf-8")
        assert "--project-only" in source
        assert "AIFACTORY_PROJECT_ONLY" in source
        project_only_block = source.split(
            'if [[ "$project_only" == "true" ]]; then\n'
            '  aif_section "03 / Project-only mode"',
            1,
        )[1].split("\nelse\n", 1)[0]
        assert 'if [[ "$project_only" == "false" ]]; then' in source
        assert "git submodule update --init --recursive --remote" in source
        assert "git pull --ff-only origin" in source
        assert 'aif_info "Skipping submodule pull, template refresh' in source
        for operation in (
            "git submodule update --init --recursive --remote",
            "git pull --ff-only origin",
            "01-aif-copy-aifactory-templates.sh",
            "03-GH-bootstrap-files-no-env-overwrite.sh",
            "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh",
            "10-GH-create-or-update-github-variables.sh",
            "git add -A",
            "git push origin",
        ):
            assert operation not in project_only_block
