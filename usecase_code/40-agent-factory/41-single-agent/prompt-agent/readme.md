# Persistent prompt agents

The shared implementation is `agent_factory/prompt.py`. The catalog creates:

- `aif-knowledge`: Foundry IQ grounding against the project's private Search
  knowledge base through a ProjectManagedIdentity MCP connection.
- `aif-reviewer`: reviews supplied evidence without inventing sources.
- `aif-docs`: public Microsoft Learn MCP example with explicit tool approval.

Use the parent directory's CLI and project-specific configuration. The default
`deploy --apply` selects these prompt agents only. Use `--agent aif-reviewer`
to deploy a single participant. Knowledge creation is blocked until managed
identity ingestion and knowledge configuration complete.

Creation uses versioned Foundry resources and routes the selected version to the
agent endpoint. No deletion runs on exit. The default model is the actual
configured deployment, not a hard-coded model name or a new global deployment.