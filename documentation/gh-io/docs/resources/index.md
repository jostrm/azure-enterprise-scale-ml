---
hide:
  - toc
---

# Azure resource library

This library lists <!-- azure-resources:count --> Azure resources of an AI Factory. <!-- azure-resources:switches --> of them have a
setting that switches them on, for a project or for the common part. The others are always there, or are an
integration. Each card names the setting, links to its explanation and says whether it is on by default.

Type in the search box, or tick the boxes. Ticks in one row widen the choice, and rows narrow each other.
**Full stack** has what an application needs around its AI: the front end, databases, a cache, Container Apps,
AKS and API Management.

<!-- azure-resources:library -->

## Always there

Every project also gets a storage account, managed identities and its own subnets. The common part of a scale
set has the network, the data lake, a container registry and Log Analytics. They have no switch.

## Switch a resource on or off

Change the setting with a tool: see [Add and update](../factory-tools/19-cli-and-api-and-usage.md), or pass
`settings` to `esaf.upsert_project(...)` as in [Enable ESAF Agent Chat](../setup/04-first-agent-chat.md). Every
setting is explained in [Every variable in variables.json](../parameters/variables.md).

Before you switch a resource off, read
[what happens when you switch a service off](../index.md#what-happens-when-you-switch-a-service-off).

Looking for code that uses a resource? Open the [code templates library](../code-templates/index.md), or
select the link on a card. The [architecture images](../architectures.md) use the same names.
