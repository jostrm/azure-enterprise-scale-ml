[Docs](../README.md) › Reference

# Folder structure

ESAF keeps your configuration in one `azurefactory` folder in your consumer repository. One folder can hold
several AI Factories. The Factory API writes these files for the existing API routes.
The optional Pipelines-only route uses the same registered layout, not a legacy copy.

## The azurefactory folder

```text
azurefactory\
  register.json                       The register: every Factory in this folder
  factories\
    acme-ai\                          One AI Factory
      factory.json
      pipelines\
        ado.json                      Or gha.json: how the Factory reaches its pipelines
      scalesets\
        001\                          One scale set
          scaleset_state.json
          projects\
            project001\               One project
              project_state.json
              variables.json          The project's settings for Dev, Stage and Prod
```

| Item | What it holds |
|---|---|
| `register.json` | Sole authoritative commit point: embeds identities, configuration, per-project variables and bindings together. |
| `factories\<key>\` | Holds one Factory. The key is the name you gave it, for example `acme-ai`. |
| `scalesets\<suffix>\` | Holds one scale set. The suffix is three digits, for example `001`. |
| `projects\projectNNN\` | Holds one project, for example `project001`. Every project lives under its scale set. |
| `variables.json` | Human-readable projection of the register's project settings, with `dev` and `stage_prod` sections. |

Dev, Stage and Prod are sections in `variables.json`, not extra folders. Keep credentials in a key vault,
never in these files.

For Pipelines-only, an explicit variables path must agree with the corresponding
embedded register object. It is not a silent override. The API-free
`bootstrap/lib/pipeline_configuration.py` generates new drafts, including their
projections; it never changes an existing root or grants deployment permission.
Configuration edits are reviewed before adoption. See the
[input, ZIP and persistence contract](maintainers/automation-and-review-flow.md#pipelines-only).

## Your consumer repository after setup

`01-start-v125-and-above.sh` adds the tools and an empty register to your consumer repository:

```text
consumer-repository\
  azure-enterprise-scale-ml\          This repository, as a submodule
  azurefactory\
    register.json                     Empty until you create a Factory
    .azurefactory\                    Local API state: never commit it
  azurefactory.sh                     Runs the azurefactory CLI
  GHA-azurefactory.sh                 Terminal entry point for GitHub Actions
  ADO-azurefactory.sh                 Terminal entry point for Azure DevOps
  .azurefactory-tools\                A local copy of the CLI and SDK
  .gitignore                          Gains one line: .azurefactory/
```

| Item | What you do with it |
|---|---|
| `azurefactory\` | Commit it. It's your Factory's configuration. |
| `azurefactory\.azurefactory\` | Leave it out of Git. It holds the API's lock and operations database. |
| `azurefactory.sh` and the two entry points | Run them from the repository root. |

Run the script again to refresh the tools. It keeps your register and your settings, and it backs up changed
tool files under `.aifactory-backups`.

**Next:** [Quickstart: Install the ESAF tools](../quickstarts/01-install-esaf.md)

Related: [Settings](settings.md) · [The six scenarios](scenarios.md) ·
[Maintainers: register starter and local API state](maintainers/automation-and-review-flow.md#register-starter-and-local-api-state)
