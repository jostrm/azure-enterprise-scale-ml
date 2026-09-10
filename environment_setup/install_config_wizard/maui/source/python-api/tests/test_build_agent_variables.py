from pathlib import Path

import yaml

from src import wizard


BUILD_AGENT_DEFAULTS = {
    "useSelfHostedBuildAgent": "false",
    "selfHostedRunnerLabel": "aifactory-admin-vm",
    "adminVMBuildAgentPool": "Default",
    "adminVMBuildAgentName": "",
}


def test_build_agent_defaults_and_mappings_are_complete():
    for key, value in BUILD_AGENT_DEFAULTS.items():
        assert wizard.DEFAULT_STATE[key] == value
        assert wizard.YAML_MAP[key] == f"variables.{key}"

    assert wizard.ENV_MAP["useSelfHostedBuildAgent"] == "USE_SELF_HOSTED_BUILD_AGENT"
    assert wizard.ENV_MAP["selfHostedRunnerLabel"] == "SELF_HOSTED_RUNNER_LABEL"
    assert wizard.ENV_MAP["adminVMBuildAgentPool"] is None
    assert wizard.ENV_MAP["adminVMBuildAgentName"] is None


def test_build_agent_values_render_to_ado_and_github_templates(tmp_path, monkeypatch):
    template_root = Path(__file__).parents[1] / "template-files"
    monkeypatch.chdir(Path(__file__).parents[1])

    state = dict(wizard.DEFAULT_STATE)
    state.update(
        {
            "useSelfHostedBuildAgent": "true",
            "selfHostedRunnerLabel": "custom-runner",
            "adminVMBuildAgentPool": "custom-pool",
            "adminVMBuildAgentName": "custom-agent",
        }
    )

    ado = yaml.safe_load("".join(wizard._render_azure_devops(state)))["variables"]
    assert ado["useSelfHostedBuildAgent"] == "true"
    assert ado["selfHostedRunnerLabel"] == "custom-runner"
    assert ado["adminVMBuildAgentPool"] == "custom-pool"
    assert ado["adminVMBuildAgentName"] == "custom-agent"

    gha = "".join(wizard._render_github_actions(state))
    assert 'USE_SELF_HOSTED_BUILD_AGENT="true"' in gha
    assert 'SELF_HOSTED_RUNNER_LABEL="custom-runner"' in gha
    assert "ADMINVMBUILDAGENTPOOL" not in gha
    assert "ADMINVMBUILDAGENTNAME" not in gha
