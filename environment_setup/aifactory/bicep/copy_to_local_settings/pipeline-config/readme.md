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

## Identity isolation

For GitHub Actions JSON-first deployments, add the non-secret
`AZURE_CLIENT_ID` for the scale set's federated user-assigned managed identity
to `variables.json`. The workflows select `tenantId` and the exact
`dev_sub_id`, `test_sub_id`, or `prod_sub_id` from JSON before **Azure login
with OpenID Connect (OIDC)**. This avoids using GitHub Environment variables
or Azure credential secrets for target selection. GitHub still supplies its
short-lived OIDC token; it is not stored in JSON.

Grant that identity only the required roles in its own Dev, Stage, and Prod
subscriptions. Do not share one identity across scale sets in
`own-subscriptions` mode.

Azure DevOps applies `variables.json` to both common and project pipeline
steps. Its `AzureCLI@2` service connection is selected before runtime JSON is
loaded, so use a distinct, pre-authorized workload-identity service connection
for each scale set. Store those connection names in that scale set's
`variables.yaml` or supply them as reviewed pipeline parameters; never put
service credentials in `variables.json`.
