# Platform automation

ESAF turns the settings you choose into a repeatable deployment. This page lists what it works out for you
and what you still decide.

## What the automation does

| Area | What ESAF does | What you decide |
| --- | --- | --- |
| Address planning | Calculates the subnets of each project from the range of the scale set and the subnets that already exist. | Give a range that is large enough and doesn't overlap your other networks. |
| Service dependencies | Checks that the services you switched on have the services they need. Private Foundry agents, for example, need AI Search, Cosmos DB and Storage. | Choose the services. Resolve what the check reports. |
| Identity and access | Creates the managed identities and assigns the roles for the project team and the services. | Name the people or the Entra ID groups of the team. |
| Settings in three formats | Maps each setting to its name in `variables.json`, in the Azure DevOps variables and in the GitHub variables. | Change a setting in one place, with a tool. |
| Naming | Builds every resource name from the Factory prefix, the project number, the region and the environment. | Choose the prefix and the suffix once, when you create the Factory. |
| Updates | Runs the same pipeline again to add a service or change a setting. | Read the plan of a change before you run it. |

## Groups and personas

A project has a team. You name its members as users or as Entra ID groups (`use_ad_groups`). The pipeline
gives the team the roles it needs on the project's services. Persona names such as team lead or data
scientist label the groups. See [Parameters](../parameters/index.md) for the settings.

## Start here

Start with [Parameters](../parameters/index.md), then use [Add and update](../factory-tools/19-cli-and-api-and-usage.md)
to make the change.

<details markdown="1">
<summary>More info</summary>

**Address ranges.** With shared subscriptions, a scale set uses a `/18` range and the third octet starts at
`0` for Dev, `64` for Stage and `128` for Prod. With own subscriptions it uses a `/20` range, with `0`, `16`
and `32`. Private DNS, routing, the VPN client pool and the access of the pipeline runner are part of the
same plan.

**Names.** Use the resource IDs that a run returns in later calls, rather than building a name from the
prefix yourself.

**Stopped runs.** When a run stops, read its status before you start it again. See
[Remove and recover](../factory-tools/20-cli-and-api-and-usage.md).

</details>
