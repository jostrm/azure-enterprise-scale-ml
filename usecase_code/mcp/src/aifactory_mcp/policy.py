"""Shared immutable policy for Foundry application callers and registration plans."""

APPLICATION_READ_ROLE = "AiFactory.Mcp.Read"
DEFAULT_APPLICATION_TOOLS = ("factory_health", "factory_capabilities", "factory_skills")
COST_APPLICATION_TOOLS = frozenset({
    "cost_default_project_idle", "cost_common_idle", "cost_monthly_project_forecast",
})
GRAPH_APPLICATION_TOOLS = frozenset({
    "graph_status", "graph_query", "architecture_search", "architecture_note", "dual_graph_context",
})
READ_ONLY_APPLICATION_TOOLS = frozenset({
    *DEFAULT_APPLICATION_TOOLS, "factory_catalog", "factory_settings",
    *COST_APPLICATION_TOOLS, *GRAPH_APPLICATION_TOOLS,
})
