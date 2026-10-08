# GitHub Actions

Choose GitHub Actions when your team uses GitHub repositories, environments and
workflows. It uses the same reviewed Factory configuration concepts as the other
clients, with GitHub-specific identity and execution setup.

## Start with a registered factory

Use [CLI, Python SDK or REST](../factory-tools/19-cli-and-api-and-usage.md) to
select `gha`, save configuration and review the exact target. Then separately
approve the supported deployment or registered Full-bootstrap workflow.

Selecting `gha` or creating a project record does not dispatch a workflow.
Registered execution requires compatible source, a reviewed binding, identity,
coordination and runner/private-network setup.

## Repository, identity and environments

| Area | What to check |
| --- | --- |
| Repository | Exact owner/name, approved visibility and source revision. |
| Azure identity | Configured OIDC/federated identity or the supported service-principal route; API keys are separate. |
| GitHub environment | Exact case-sensitive name, required secrets/variables and protection rules. |
| Runner | Supported labels/image, registration and network reachability. Registration is not an Azure deployment login. |
| Azure target | Existing tenant/subscription, region, selected environment and required permissions. |

GitHub full-bootstrap paths can create environment names `Dev`, `Stage`, `Prod`
and store the logical-to-actual mapping in `AIFACTORY_GITHUB_ENVIRONMENTS`.
That does not mean Stage/Prod Azure infrastructure has been deployed.
Existing environments and OIDC subjects must not be silently renamed.

## Configuration and private access

GitHub `.env` template names are often uppercase; JSON/YAML names can differ.
Use [Parameters](../parameters/advanced.md) instead of mechanical case conversion.
Editing a local `.env` does not publish its values to GitHub automatically.

Private endpoints require working DNS, routes and runner access. Hosted runners
are not automatically able to reach private services. Full bootstrap and
runner-only setup have different prerequisites; runner-only setup expects the
selected existing network resources.

## Observe rather than retry

Read the catalog job and the exact GitHub run. `workflow status/watch` is
read-only; reconnecting the watch does not rerun the workflow.
A timeout stops local waiting, not the Azure operation.

[Status and recovery examples](../factory-tools/20-cli-and-api-and-usage.md)

<details markdown="1">
<summary>More info</summary>

Shared-VNet project allocation uses the selected planner and existing subnet
inventory. Available aligned gaps, fragmentation, reserved gateway/DNS ranges
and exact project ownership matter. Existing subnets are not renamed or moved
just to make a new allocation fit. Serialize writers of a shared network.

Simple-mode and advanced/full-bootstrap paths have different address and
resource-selection contracts. New optional Application Gateway choices do not
automatically adopt a customer's existing gateway. Read the
[specific parameter contract](../parameters/advanced.md#simple-mode-technical-contract).

The project001 Dev MCP/AI Gateway integration is a later opt-in pipeline step,
with explicit image, identity and network prerequisites. False skips that step,
not resource deletion. [Component details](../parameters/advanced.md#mcp-and-ai-gateway-parameters).

</details>

<details markdown="1">
<summary>Alternative and Legacy ways</summary>

Existing legacy consumers use matching root launchers:

- `GHA-create-new-aifactory-scaleset.sh` for its full creation path.
- `GH-update-aifactory-and-run-project.sh` for project/template updates;
  `GHA-update-aifactory-and-run-project.sh` forwards to it.
- `--project-only` skips the library/template update part.
- `--aifactory-env dev|stage|prod` chooses the project environment.

Legacy create defaults to `124`; update normally inherits the saved version.
Select `--aifactory-version main` explicitly when adopting development source.
The actual run is tied to the reviewed commit even as `main` advances.

Normal launcher runs can commit/push, configure identities, create billable
resources and dispatch workflows. `--prepare-only` is not a read-only preview;
`--no-wait` does not prove completion. Neither route is a fallback for a blocked
registered operation.

[Complete launcher inputs](../parameters/advanced.md#bash-create-and-update-contract) |
[Current GHA templates](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/copy_to_local_settings/github-actions) |
[Setup guide](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/24-end-2-end-setup.md)

</details>
