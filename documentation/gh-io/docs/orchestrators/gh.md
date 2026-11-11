# GitHub Actions

Choose GitHub Actions when your team keeps its repositories, environments and workflows on GitHub. The
Factory, its settings and the Bicep templates are the same as with Azure DevOps.

## Start with a Factory

Create the Factory with the `gha` orchestrator: follow [Create your AI Factory](../setup/02-create-factory.md),
or [Add and update](../factory-tools/19-cli-and-api-and-usage.md) when you want to review each step yourself.

## Repository, identity and environments

| Area | What to have ready |
| --- | --- |
| Repository | Its owner and name, and whether it is private or public. |
| Azure identity | A federated identity (OIDC) for the workflows, or a service principal. |
| GitHub environment | Its exact name (upper and lower case matter), with its variables, secrets and protection rules. |
| Runner | A self-hosted runner that reaches the private endpoints, when the Factory is private. |
| Azure target | The tenant, the subscription, the region and the environment. |

Full bootstrap creates the GitHub environments `Dev`, `Stage` and `Prod`, and stores which GitHub environment
belongs to which Factory environment in the repository variable `AIFACTORY_GITHUB_ENVIRONMENTS`. Creating a
GitHub environment deploys nothing to Azure. Keep the names of existing environments, because the federated
identity is bound to them.

When you enroll an existing repository, the federated identity is bound to `environment:<auth_namespace>`. If
that name isn't `dev`, `stage` or `prod` and the variable doesn't exist yet, enrollment creates
`AIFACTORY_GITHUB_ENVIRONMENTS` with that name. An existing variable is never overwritten. The plan warns when
it names a different environment.

The Add-Factory-Agent and project dashboard workflows read the operating system of the self-hosted runner
from `selfHostedRunnerOS` in `variables.json`. Without that setting they use the runner in
`azurefactory/register.json` (Linux), and otherwise Windows.

## Settings and private access

GitHub variables have uppercase names, and `variables.json` has its own names. The
[Parameters reference](../parameters/advanced.md) lists both for every setting. A change in a local `.env`
file reaches the workflows after the variables are published to GitHub.

With private networking, use a self-hosted runner inside the network. A GitHub-hosted runner can't reach
private endpoints.

## Follow the run

Follow the job that a call returns, or the GitHub run itself. `workflow status` and `workflow watch` only
read: starting the watch again never starts the workflow again. When a watch times out, the run in Azure
continues.

[Status and recovery examples](../factory-tools/20-cli-and-api-and-usage.md)

<details markdown="1">
<summary>More info</summary>

**Subnets.** In a shared VNet, each new project gets its subnets from the free ranges. Existing subnets keep
their names and ranges. Add one project at a time to a shared network.

**Simple mode.** Simple mode and Full bootstrap take different inputs for addresses and services. Simple mode
can create a new Application Gateway. To use a gateway you already have, leave that option off. See the
[simple mode reference](../parameters/advanced.md#simple-mode-technical-contract).

**MCP and AI gateway.** The Factory MCP server and the AI gateway are optional steps of the project 001 Dev
pipeline. See the [settings](../parameters/advanced.md#mcp-and-ai-gateway-parameters).

</details>

<details markdown="1">
<summary>Earlier way: the launcher scripts</summary>

A repository that was set up with v1.24 has these scripts in its root:

- `GHA-create-new-aifactory-scaleset.sh` creates a Factory with its identities, repository and workflows.
- `GH-update-aifactory-and-run-project.sh` updates the templates and runs the project workflow.
  `GHA-update-aifactory-and-run-project.sh` calls the same script.
- `--project-only` runs the project workflow without updating the templates.
- `--aifactory-env dev|stage|prod` selects the environment.

Create uses version `124` unless you give another, and update keeps the version that was saved. Pass
`--aifactory-version main` to use the current development version.

A launcher run commits and pushes, sets up identities, creates Azure resources that cost money and starts
workflows. `--prepare-only` does all of that except the deployment. With `--no-wait` the script returns before
the workflows end, so follow them on GitHub.

[Complete launcher inputs](../parameters/advanced.md#bash-create-and-update-contract) |
[Current GHA templates](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions) |
[Setup guide](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/24-end-2-end-setup.md)

</details>
