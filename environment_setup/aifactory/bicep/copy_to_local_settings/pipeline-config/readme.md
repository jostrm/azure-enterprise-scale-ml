# Pipeline JSON configuration

Provide one full configuration file for Dev and one shared file for Stage and
Prod. The configuration object must contain exactly one of these sections:

- `dev`: used only by Dev deployments.
- `stage_prod`: used by both Stage and Prod deployments.

Use the route-specific examples as the complete configuration schema:

| Orchestrator | Dev file | Shared Stage/Prod file | Variables |
|---|---|---|---:|
| Azure DevOps | `azure-devops.project-config.dev.example.json` | `azure-devops.project-config.stage_prod.example.json` | 304 |
| GitHub Actions | `github-actions.project-config.dev.example.json` | `github-actions.project-config.stage_prod.example.json` | 300 |

The Azure DevOps schema is sourced from the Configuration Wizard's
`template-files/variables.json`. The GitHub Actions schema uses the 300 unique
variables from its `.env` template; duplicate assignments in that template are
represented once.

GitHub Actions reserves the five `GITHUB_*` bootstrap variables, so they stay
represented in the 300-variable schema but are not written to `GITHUB_ENV`
during a project deployment. They are used when bootstrapping a repository, not
when deploying a project.

These files contain non-secret deployment configuration. Keep credentials and
other secret values in Azure DevOps service connections, Azure DevOps secret
variables, GitHub Environments, or Key Vault.
