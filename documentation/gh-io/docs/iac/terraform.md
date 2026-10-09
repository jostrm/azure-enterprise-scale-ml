# Bring your own infrastructure

Already managing shared Azure resources with Terraform? You can use supported
AI Factory **existing-resource inputs** to integrate with that estate.
Keep ownership clear: Terraform and AI Factory must not independently manage
the same resource without an explicit plan.

!!! note "Not a second complete deployment engine"
    The repository's `environment_setup/aifactory/terraform/readme.md` remains
    a TODO for Bicep-equivalent behavior. Do not assume complete Terraform
    templates or registered-runtime parity are implemented.

## A practical split

Your platform team may provide subscriptions, hub networking, DNS, storage or
other common services. The AI Factory's supported Bicep/project route then uses
approved references where the chosen template supports them.

| Input | What it identifies |
| --- | --- |
| `vnetNameFull_param`, `vnetResourceGroup_param` | Existing VNet and its resource group |
| `commonResourceGroup_param` | Common resource-group reference |
| `datalakeName_param` | Existing data-lake account |
| `kvNameFromCOMMON_param` | Existing common Key Vault |
| `BYO_subnets` and service subnet names | Use the reviewed existing subnet layout |
| `centralDnsZoneByPolicyInHub` and `privDns*` settings | Central private-DNS design and location |

See [all parameters](../parameters/advanced.md) for exact names and conditions.
Supplying a reference does not grant access, create a peering, or transfer
resource ownership.

## Before integrating

1. Agree which tool owns each resource and its state.
2. Confirm exact IDs, subscriptions, address ranges, DNS and private routes.
3. Give the deployment identity only the required permissions.
4. Review AI Factory's deployment and deletion plans with those boundaries.

Never allow whole-group deletion to remove resources still owned by another
project or tool. An unsupported combination should remain blocked.

<details markdown="1">
<summary>More info</summary>

[Terraform status in source](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/terraform/readme.md) |
[Bicep route](bicep.md) |
[Factory operations](../factory-tools/19-cli-and-api-and-usage.md)

BYO integration is not an automatic translation of Terraform state into the
registered catalog. Importing configuration and proving deployment ownership
are separate tasks.

</details>
