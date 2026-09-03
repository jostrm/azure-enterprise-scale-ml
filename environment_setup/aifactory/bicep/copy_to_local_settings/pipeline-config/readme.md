# Pipeline JSON configuration

The canonical configuration is
`environment_setup/aifactory/variables.json`; do not create per-orchestrator or
per-environment JSON copies. It contains one `dev` object sourced from
`azure-devops/esml-yaml-pipelines/variables/variables.yaml` and is the shared
baseline for Dev, Stage, and Prod. Add a `stage_prod` object only when an
explicit Stage/Prod override is required.

These files contain non-secret deployment configuration. Keep credentials and
other secret values in Azure DevOps service connections, Azure DevOps secret
variables, GitHub Environments, or Key Vault.
