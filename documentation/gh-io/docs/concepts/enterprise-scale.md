# Enterprise design and scale

An AI Factory lets many teams reuse one common infrastructure, while every project keeps its own resources
in each environment.

## Scale by projects and scale sets

A scale set groups projects that share one network, in one environment and subscription. It has nothing to
do with Azure Virtual Machine Scale Sets. A project names the scale set it runs in.

How many projects fit in a scale set depends on its address range, the subnets that already exist and your
service quotas. When a scale set is full, [add a scale set](../setup/add-scale-set.md).

## Environments and subscriptions

| Choice | Meaning |
| --- | --- |
| Shared subscriptions | Environments can share subscriptions while retaining explicit identity and network targets. |
| Own subscriptions | Use the selected subscriptions for the intended isolated targets. |
| Existing enterprise network | Reuse approved hub, DNS and subnet arrangements through supported inputs. |

Add only the environments you need. Dev is created first. Stage and Prod are created when you ask for them,
in subscriptions that already exist.

## Watch Dev, Stage and Prod

Follow a versioned candidate through development, evaluation, release approval and monitoring. The
animation shows the recommended process. Promote code and models between environments. Keep production data
and secrets where they are.

<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="../../assets/animations/promotion.png">
  <img src="../../assets/animations/promotion.gif" alt="A candidate moves from Dev to Stage evaluation and separate production approval, followed by monitoring and governed feedback." width="1400" height="910" loading="lazy">
</picture>

[Animated SVG](../assets/animations/promotion.svg) |
[GIF](../assets/animations/promotion.gif) |
[Still image](../assets/animations/promotion.png)

## Review each design concern

| Concern | What to check |
| --- | --- |
| Security | Identity, least privilege, data access, private connectivity and supported encryption options. |
| Reliability | Dependencies, backup/recovery, regional service support and failure handling. |
| Cost | Selected services, environment SKUs, model capacity and usage/cost reporting. |
| Operations | Reviewed changes, exact run tracking, diagnostic settings and ownership. |
| Performance | Workload needs, compute/service sizing, scaling limits and available capacity. |

These are the pillars of the
[Well-Architected guidance for AI workloads](https://learn.microsoft.com/en-us/azure/well-architected/ai/personas).

## Plan network space before deployment

Give each environment its own range, and keep the ranges apart from your existing networks and from the VPN
client pool. ESAF plans subnets inside the range you give. It doesn't resize a VNet that already exists.

The [Parameters checklist](../parameters/standard.md) and the
[platform automation guide](intelligence.md) list the settings. With private networking, the pipeline runner
and your users also need a route and DNS to reach the private endpoints. See
[Hub and network modes](../reference/hub-and-network-modes.md).

<details markdown="1">
<summary>More info</summary>

With shared subscriptions, a scale set uses a `/18` range and the third octet starts at `0` for Dev, `64` for
Stage and `128` for Prod. With own subscriptions it uses a `/20` range, with `0`, `16` and `32`.

Which services and models you can use depends on the Azure region and cloud. Check the region of your
Factory before you switch on a service.

[Registered operations](../factory-tools/19-cli-and-api-and-usage.md) |
[Shared template parameters](../parameters/advanced.md)

</details>
