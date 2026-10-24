"""The AI Factory Agent steps (chat agent, MCP and AI Gateway, live voice) run after the region reports are published.

An agent failure then never hides the infrastructure result: the region reports describe the deployment, and the
agent steps follow as the last tasks of the project job, in their own dependency order.
"""
from __future__ import annotations

from domain.pipeline_contracts import ADO_SERVICES, GHA_PHASE, load_pipeline

ADO_AGENT_TEMPLATES = (
    "- template: job-factory-chat-agent.yaml",
    "- template: job-aifactory-mcp-ai-gateway.yaml",
    "- template: job-aifactory-agent-live-voice.yaml",
)
GHA_AGENT_STEPS = (
    "Deploy Factory Chat Agent in Foundry",
    "Deploy AI Factory MCP and AI Gateway SKU (project001 Dev)",
    "Deploy AI Factory Agent live voice (any project, Dev)",
)
GHA_CLEANUP = "Remove run-specific reviewed configuration"


def test_ado_agent_templates_are_the_last_templates_after_the_region_reports():
    services = ADO_SERVICES.read_text(encoding="utf-8")
    positions = [services.index(template) for template in ADO_AGENT_TEMPLATES]
    assert services.index("region-report-steps.yaml") < positions[0]
    assert positions == sorted(positions)
    assert services.rindex("- template: ") == positions[-1]


def test_github_agent_steps_follow_the_region_reports_and_precede_only_the_cleanup():
    names = [step.get("name") for step in load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["steps"]]
    first = names.index(GHA_AGENT_STEPS[0])
    assert names.index("Publish AI Factory region reports") < first
    assert names[first:first + len(GHA_AGENT_STEPS)] == list(GHA_AGENT_STEPS)
    assert names[first + len(GHA_AGENT_STEPS):] == [GHA_CLEANUP]
