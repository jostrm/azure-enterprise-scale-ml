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

GitHub runner **registration** uses a short-lived token minted by authenticated
`gh`; Azure managed identity/OIDC is the separate **deployment** login. A GitHub
runner's name or online status cannot establish whether the historical `gh`
session used an OAuth login, PAT or installation token. Newly provisioned Linux
runner VMs have no managed identity attached. Existing Windows admin-VM identity
settings are preserved.

New full bootstrap creates GitHub environments **Dev**, **Stage**, **Prod**.
The numeric `/settings/environments/<id>` URL is an environment ID, not its name.
The repository variable `AIFACTORY_GITHUB_ENVIRONMENTS` maps the unchanged logical
selectors `dev`, `stage`, `prod` to exact GitHub names; Azure still uses
`dev`, `test`, `prod`. Existing lowercase environments keep their names and
case-sensitive OIDC subjects. Updated workflows without the mapping retain
their legacy lowercase behavior. No remote environment is renamed, deleted or
stripped of protection rules. Other named environments are left untouched and do
not require enrollment to run full bootstrap. To deliberately use a custom
environment, supply a reviewed complete `AIFACTORY_GITHUB_ENVIRONMENTS` mapping,
for example `{"dev":"aifactory-existing","stage":"Stage","prod":"Prod"}`. Bootstrap refuses
to overwrite a saved mapping or a conflicting federated credential; changing
either requires a separately reviewed migration.

Full bootstrap can create/ensure its bootstrap resource group, deployment
identity (`AIF_IDENTITY_MODE=c`), common infrastructure and missing Linux runner.
`mi` and `sp` instead select existing identities. The runner-only preparation
command intentionally requires the selected common resource group and subnet to
exist; it is not full bootstrap.
Advanced Mode reuses existing resource groups and deployment identities rather
than recreating them. Simple Mode deliberately requires a fresh bootstrap/common
scope; use Advanced Mode to resume an existing scope.
All subscription IDs must already exist; bootstrap does not create subscriptions.
The existing MAUI/API full-bootstrap route remains independent of optional
registered exact-scope enrollment.

The initial team group is created/ensured unless `AIF_TEAM_GROUP_ID` supplies an
existing group. Technical administrators default to that team for compatibility.
Choose `AIF_ADMIN_GROUP_MODE=separate` to supply `AIF_ADMIN_GROUP_ID`, or
create/ensure `AIF_ADMIN_GROUP_NAME` with `AIF_ADMIN_MEMBER_EMAIL`.
Supplied group IDs skip membership changes; creation/membership and role
assignments still require the caller's normal Entra/Azure permissions.

!!! note "Integrated VPN and project allocation"
    **Advanced Mode with integrated VPN** keeps `GatewaySubnet` at the end of
    the common VNet. `subnetCalc_v2.ps1` now allocates aligned free IPv4 gaps
    across all VNet prefixes, largest subnet first with stable logical-name ties.
    Existing managed `snt-prj<projectNumber>-...` subnets retain their exact CIDRs, even when defaults
    change; other subnets are reserved, never renumbered. Exhaustion, fragmentation,
    malformed inventory, and unsupported multi-prefix project subnets fail before
    parameter output. Multiple IPv4 prefixes on unrelated subnets are reserved;
    IPv6 allocation is not supported. Serialize writers sharing the same VNet.
    **Simple Mode** instead reserves `172.16.1.0/27` for the gateway and
    `172.16.1.32/28` for DNS, and checks room for a full project in its fixed
    `172.16.0.0/20`, using the same gap policy rather than a tail cursor.
    The offline `10.113.0.0/18` regression retains gateway `10.113.63.224/27`
    and supports three full project allocations and repeat updates; client pool
    `172.31.240.0/24` is separate, not a VNet subnet. This is not Azure deployment proof.
    Do not change an integrated selection to an external hub to bypass allocation.

    Canonical GitHub Actions and ADO project templates pass the project number to
    the allocator in the accelerator submodule. Existing consumers must adopt the
    reviewed published accelerator revision and refreshed templates together.
    Registered Full bootstrap's API frozen project projection already uses free-gap
    allocation with exact project ownership checks, reading subnet sizes from the
    pinned PowerShell source rather than invoking its old append path. API creation
    sources snapshot `bootstrap` and `environment_setup/aifactory`; after publishing,
    synchronize the exact reviewed source and rebuild packaged clients where needed.
    Editing the canonical working tree does not update existing pinned snapshots.

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
