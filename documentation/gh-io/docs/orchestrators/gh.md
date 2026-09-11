# GitHub Actions

Use the GitHub consumer repository for this route; it is separate from an Azure
DevOps repository. Maintain one complete project `variables.json` with `dev` and
`stage_prod`, or use the route's `.env` settings. See
[configuration and API](../parameters/index.md) and [all variables](../parameters/advanced.md).

## Create a new factory scale set

Run the current published create launcher, supplying a separate destination:

```bash
bash ./GHA-create-new-aifactory-scaleset.sh --repo-root "C:/work/my-gha-factory"
```

The source copy is under `bootstrap/`; installed consumer copies may be at the
repository root. The normal bootstrap prepares the repository, identity,
configuration, common infrastructure and initial project. It can create billable
resources and publish repository changes. Read its summary before accepting.

| Option | Meaning |
|---|---|
| `--aifactory-version main` | Explicit template selection; these create wrappers currently default to `main` |
| `--dry-run` | Collect/validate answers without executing the normal full-bootstrap mutations |
| `--non-interactive --yes` | Use documented `AIF_*` inputs and accept execution; authentication must already be available |
| `--prepare-only` | Prepares Azure/identity/configuration/automation; **not** a read-only preview |
| `--no-wait` | Dispatch without waiting; does not prove deployment success |

The specialized `AIF_SIMPLE_MODE=true` contract has its own fixed inputs and
preview restrictions; see [the full reference](../parameters/advanced.md).

## Update or run an existing project

From the selected consumer repository:

```bash
# Refresh AI Factory/templates, then run the project workflow.
bash ./GH-update-aifactory-and-run-project.sh --aifactory-version main

# Run the existing project pipeline without refreshing templates.
bash ./GH-update-aifactory-and-run-project.sh --project-only
```

`GHA-update-aifactory-and-run-project.sh` is the equivalent alias. Default update
uses `main`; `--project-only` preserves the installed source. Scripts can prompt
for configuration, commit/push or authentication; they are not automatically
unattended merely because they are invoked from another program.

API-reviewed runs bind `AIFACTORY_TARGET_ENVIRONMENT`, `AIFACTORY_PROJECT_NUMBER`
and `AIFACTORY_PROJECT_CONFIG` to the selected target. Use the API prepare/start
flow for those runs; do not reuse an old confirmation for another project.
The configuration is transported through protected per-run configuration, not
committed as a public JSON file.

## Authentication and configuration

Local execution needs Git Bash, Azure CLI, GitHub CLI, host Python and access to
the intended repository and Azure subscriptions. Pipeline authentication uses
the configured OIDC/federated identity or the supported service-principal route.
Keep credentials in the required secret stores, never in `.env.template` or docs.

The route template is
[`github-actions/.env.template`](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template).
It uses uppercase names; JSON/YAML often use different names. Do not mechanically
uppercase JSON keys. Workflow files run under `.github/workflows`; use the
documented entrypoint and verify the exact workflow/run, rather than assuming
every push deploys.

For a registered exact-scope lifecycle operation, the additional
`bootstrap/GHA-azurefactory.sh` wrapper consumes a trusted, protected reviewed
manifest. It does not replace full bootstrap or initialize a register. It requires
a published compatible provider, authentication and target-lock enrollment.

!!! note "Source versions"
    Use a matching published release of scripts, helpers and pipeline templates.
    `125` means `release/v1.25`; `main` is an explicit moving branch whose reviewed
    commit is pinned for execution. Local unpublished changes are not available
    to a remote workflow until separately published.
