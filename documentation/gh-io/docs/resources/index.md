---
hide:
  - toc
---

# Azure resource library

Every Azure service that a project or the common part of your AI Factory can switch on. Each card names the
setting in `variables.json` and says whether it is on by default.

Type in the search box, or select a category, a kind or where the resource is deployed. **Full stack** has
what an application needs around its AI: the front end, databases, a cache, Container Apps, AKS and API
Management.

<!-- azure-resources:library -->

## Always there

Every project also gets a Key Vault, a storage account, managed identities and its own subnets. The common
part of a scale set has the network, the data lake, a Key Vault and monitoring. They have no switch.

## Switch a service on or off

Change the setting with a tool: see [Add and update](../factory-tools/19-cli-and-api-and-usage.md), or pass
`settings` to `esaf.upsert_project(...)` as in [Enable ESAF Agent Chat](../setup/04-first-agent-chat.md). Every
setting is explained in [Every variable in variables.json](../parameters/variables.md).

Before you switch a service off, read
[what happens when you switch a service off](../index.md#what-happens-when-you-switch-a-service-off).
