# Bring your own infrastructure

Do you already manage shared Azure resources with Terraform? Point ESAF at those resources with the settings
below. Decide which tool owns each resource, so that Terraform and ESAF never change the same one.

!!! note "ESAF deploys with Bicep"
    ESAF has no Terraform templates of its own. You keep Terraform for the resources it already manages, and
    ESAF deploys the rest with Bicep.

## A practical split

Your platform team provides subscriptions, the hub network, DNS, storage or other common services. ESAF then
uses them through these settings.

| Input | What it identifies |
| --- | --- |
| `vnetNameFull_param`, `vnetResourceGroup_param` | Existing VNet and its resource group |
| `commonResourceGroup_param` | Common resource-group reference |
| `datalakeName_param` | Existing data-lake account |
| `kvNameFromCOMMON_param` | Existing common Key Vault |
| `BYO_subnets` and the subnet names | Use subnets that already exist |
| `centralDnsZoneByPolicyInHub` and `privDns*` settings | Central private-DNS design and location |

See [all parameters](../parameters/advanced.md) for the exact names and conditions. Give the deployment
identity access to each resource you name.

## Before you integrate

1. Agree which tool owns each resource and its state.
2. Collect the IDs, subscriptions, address ranges, DNS zones and routes.
3. Give the deployment identity only the permissions it needs.
4. Read what a Factory or project deletion removes, so that it stays away from the resources Terraform owns.
   See [Clean up](../setup/05-clean-up.md).

<details markdown="1">
<summary>More info</summary>

[Bicep](bicep.md) |
[Add and update](../factory-tools/19-cli-and-api-and-usage.md)

ESAF doesn't read Terraform state. You name each existing resource in the settings.

</details>
