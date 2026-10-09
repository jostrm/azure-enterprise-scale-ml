# Enterprise design and scale

AI Factory helps teams reuse common infrastructure while keeping project and
environment choices explicit. The resulting design still needs your
organization's security, network, reliability and cost review.

## Scale by projects and scale sets

An AI Factory scale set groups an environment, subscription and network setup.
It is **not Azure VM Scale Sets**. A project selects where it runs through its
Dev/Stage/Prod placements.

There is no universal "200-300 projects per scale set" guarantee. Capacity
depends on configured project limits, address ranges, existing subnets and
service quotas. Add another scale set when the reviewed design requires it.

## Environments and subscriptions

| Choice | Meaning |
| --- | --- |
| Shared subscriptions | Environments can share subscriptions while retaining explicit identity and network targets. |
| Own subscriptions | Use the selected subscriptions for the intended isolated targets. |
| Existing enterprise network | Reuse approved hub, DNS and subnet arrangements through supported inputs. |

Register only the environments you need. Stage and Prod are not created simply
because Dev exists, and a subscription reference does not create a subscription.

## Watch Dev, Stage and Prod

Follow a versioned candidate through development, evaluation, release approval
and observation. This is an illustrative recommended process, not an executable
promotion workflow. Promote reviewed artifacts, not production data or secrets.

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

These align with [Well-Architected guidance](https://learn.microsoft.com/en-us/azure/well-architected/ai/personas);
they are not a blanket production or compliance certification.

## Plan network space before deployment

Use aligned, non-overlapping ranges for selected environments, existing networks
and VPN client pools. Address planning does not resize an existing VNet, move
subnets or establish connectivity.

The [Parameters checklist](../parameters/standard.md) and
[platform automation guide](intelligence.md) explain the supported planning
inputs. Private endpoints alone do not prove that a runner or user can reach a service.

<details markdown="1">
<summary>More info</summary>

The shared `/18` planning templates use environment selectors `0`, `64`, `128`;
the own-subscription `/20` pattern uses `0`, `16`, `32`. Existing allocations,
additional prefixes and provider requirements must still be checked.
Do not copy older non-aligned examples as a deployment plan.

Service/API availability varies across Azure regions, Government and Sovereign
clouds. Validate the exact route and service set for the chosen cloud rather than
assuming Azure Public Cloud examples apply unchanged.

[Registered operations](../factory-tools/19-cli-and-api-and-usage.md) |
[Shared template parameters](../parameters/advanced.md)

</details>
