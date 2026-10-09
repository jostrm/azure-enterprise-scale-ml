# Platform automation

AI Factory automation helps turn selected settings into a repeatable plan.
It is not a self-aware system, and it does not replace your network, security
or deployment approvals.

## What the automation does

| Area | Help provided | Your responsibility |
| --- | --- | --- |
| Address planning | Calculates supported project subnet layouts from the selected ranges and existing allocations. | Supply enough non-overlapping address space and verify connectivity. |
| Service dependencies | Checks the selected service bundle and related settings. | Choose a supported architecture and resolve blockers. |
| Identity and access | Applies configured identities, role assignments and storage permissions through supported steps. | Approve least-privilege scope and supply required privileges. |
| Configuration translation | Maps supported JSON/YAML/GitHub names for the chosen route. | Use the correct input and avoid conflicting manual copies. |
| Naming | Uses configured naming and salts where required. | Preserve identity and handle existing-name/ownership conflicts. |
| Updates | Reviews and applies supported changes to existing targets. | Inspect the plan; do not assume a re-run leaves every resource untouched. |

## Groups and personas

The published templates support group principals and persona-labelled settings.
Labels alone do not prove that a complete least-privilege permission policy has
been applied.

Newer nine-persona `groups-v1` work described in local addenda is separate from
the older release snapshot. Check the published source and installed host
before assuming that policy, seeding and migration are available together.
Never grant roles merely because a document or assistant suggests them.

## Choose the supported path

Start with [Parameters](../parameters/index.md), then use the
[reviewed tool workflow](../factory-tools/19-cli-and-api-and-usage.md).
A service flag requests behavior; it does not itself prove deployment,
connectivity or cleanup.

<details markdown="1">
<summary>More info</summary>

The shared `/18` planning pattern uses aligned Dev/Stage/Prod selectors
`0`, `64`, `128`. Own-subscription `/20` plans use `0`, `16`, `32`.
Planning does not move existing subnets or resize a VNet. Private DNS, routing,
VPN client pools and the runner's access must also be checked.

Names and salts reduce collisions but are not a universal uniqueness guarantee.
Use recorded resource IDs for later operations rather than reconstructing a
target from a prefix.

Scoped review records, compatible runtime contracts and exact operation
versions protect execution. They are not permission to retry an uncertain write.
See [removal and recovery](../factory-tools/20-cli-and-api-and-usage.md).

</details>
