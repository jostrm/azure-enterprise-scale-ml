"""Agent-only pipelines (ADO and GitHub Actions), on the AI gateway pipeline's principle: a small manual pipeline that
deploys only the AI Factory Agent chat (step 70 Foundry chat agent, step 72 live voice) in Dev, without the hour of
infrastructure the project pipeline runs first. Both call the same entry as the terminal route
(ADO-/GHA-azurefactory.sh -addAIFactoryAgentChat -toProject NNN), signed in as the pipeline identity."""
from __future__ import annotations

from base.config import CLS, REPO_ROOT
from domain.pipeline_contracts import ADO_ROOT, load_pipeline

ADO = ADO_ROOT / "esml-infra-project" / "add-factory-agent.yaml"
GHA = CLS / "github-actions" / "add-factory-agent.yml"
ENTRY = "azure-enterprise-scale-ml/bootstrap/lib/agent_chat_entry.py"
ROUTING = "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/deploy-dashboards-only.py"


def ado_steps():
    pipeline = load_pipeline(ADO)
    job = pipeline["stages"][0]["jobs"][0]
    return pipeline, job, job["strategy"]["runOnce"]["deploy"]["steps"]


def test_the_entry_both_pipelines_call_exists():
    assert (REPO_ROOT / ENTRY.split("/", 1)[1]).is_file() and (REPO_ROOT / ROUTING.split("/", 1)[1]).is_file()


def test_ado_pipeline_is_manual_dev_only_with_the_agent_parameters():
    pipeline, job, _ = ado_steps()
    assert pipeline["trigger"] == "none" and pipeline["pr"] == "none"
    parameters = {item["name"]: item for item in pipeline["parameters"]}
    assert parameters["projectNumber"]["default"] == "001"
    assert parameters["configFile"]["default"] == "aifactory/variables.json"
    assert parameters["mode"]["values"] == ["plan", "apply"] and parameters["mode"]["default"] == "apply"
    assert parameters["runnerSelection"]["default"] == "from-config"
    assert [stage["stage"] for stage in pipeline["stages"]] == ["Dev_Agent_Chat"]
    assert pipeline["stages"][0]["variables"]["dev_test_prod"] == "dev"
    assert job["environment"] == "Dev"
    pool = str(job["pool"])
    assert "adminVMBuildAgentPool" in pool and "Agent.Name -equals" in pool and "runnerSelection" in pool


def test_ado_pipeline_runs_only_the_agent_entry_with_the_dev_service_connection():
    _, _, steps = ado_steps()
    assert steps[0]["checkout"] == "self" and steps[0]["submodules"] == "recursive"
    tasks = [step for step in steps if step.get("task")]
    assert [step["task"] for step in tasks] == ["AzureCLI@2"], "no Bicep, no infrastructure: only the agent entry"
    task = tasks[0]
    assert task["inputs"]["azureSubscription"] == "${{ variables.dev_service_connection }}"
    script = task["inputs"]["inlineScript"]
    assert ENTRY in script and " ado " in script and "--to-project" in script and "--config" in script
    assert task["env"]["AGENT_PROJECT"] == "${{ parameters.projectNumber }}"
    assert task["env"]["AGENT_CONFIG_FILE"] == "${{ parameters.configFile }}"
    assert task["env"]["AGENT_MODE"] == "${{ parameters.mode }}" and '"$AGENT_MODE" = "apply"' in script


def test_github_workflow_routes_offline_then_runs_the_agent_entry_with_oidc():
    workflow = load_pipeline(GHA)
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["project_number"]["default"] == "001"
    assert inputs["config_file"]["default"] == "aifactory/variables.json"
    assert inputs["mode"]["options"] == ["plan", "apply"] and inputs["mode"]["default"] == "apply"
    assert inputs["runner_selection"]["default"] == "from-config"
    assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    configure, agent = workflow["jobs"]["configure"], workflow["jobs"]["agent"]
    assert configure["runs-on"] == "ubuntu-latest"
    routing = " ".join(step.get("run", "") for step in configure["steps"])
    assert "deploy-dashboards-only.py" in routing and "--ci-output github" in routing and "--runner-selection" in routing
    assert agent["needs"] == "configure" and agent["runs-on"] == "${{ fromJSON(needs.configure.outputs.runs_on) }}"
    assert "dev" in agent["environment"]
    login = next(step for step in agent["steps"] if step.get("uses") == "azure/login@v2")
    assert login["with"]["client-id"] == "${{ secrets.AZURE_CLIENT_ID }}"
    run = next(step for step in agent["steps"] if "agent_chat_entry.py" in step.get("run", ""))
    assert "agent_chat_entry.py" in run["run"] and " gha " in run["run"] and "--to-project" in run["run"]
    assert run["env"]["AGENT_MODE"] == "${{ inputs.mode }}" and '"$AGENT_MODE" = "apply"' in run["run"]



def test_both_pipelines_can_skip_the_knowledge_index_for_code_only_changes():
    pipeline, _, steps = ado_steps()
    parameters = {item["name"]: item for item in pipeline["parameters"]}
    assert parameters["refreshKnowledge"]["type"] == "boolean" and parameters["refreshKnowledge"]["default"] == "true"
    task = next(step for step in steps if step.get("task") == "AzureCLI@2")
    assert task["env"]["AGENT_REFRESH_KNOWLEDGE"] == "${{ parameters.refreshKnowledge }}"
    assert "--skip-knowledge" in task["inputs"]["inlineScript"]
    workflow = load_pipeline(GHA)
    assert workflow["on"]["workflow_dispatch"]["inputs"]["refresh_knowledge"]["default"] == "true"
    run = next(step for step in workflow["jobs"]["agent"]["steps"] if "agent_chat_entry.py" in step.get("run", ""))
    assert run["env"]["AGENT_REFRESH_KNOWLEDGE"] == "${{ inputs.refresh_knowledge }}" and "--skip-knowledge" in run["run"]
