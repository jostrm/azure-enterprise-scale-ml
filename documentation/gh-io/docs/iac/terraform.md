# IaC — BYO Terraform

The AI Factory natively uses **Azure Bicep** for IaC. However, if your organisation already has Terraform-based infrastructure, the AI Factory supports a **Bring Your Own Terraform (BYO Terraform)** mode.

---

## BYO Terraform Philosophy

BYO Terraform means: **use your existing Terraform for shared/common infrastructure, and let the AI Factory Bicep handle the AI Factory-specific project resources**.

Typical split:

| Managed by Terraform | Managed by AI Factory Bicep |
|---|---|
| Hub VNet, firewall, DNS zones | Project VNets, subnets (or BYO subnets) |
| Shared Key Vaults (seeding KV) | Project Key Vaults |
| Shared ACR | Project ACR (or shared, configurable) |
| Existing subscriptions, resource groups | AI Factory Common RG + Project RGs |

---

## Integration Points

Configure the following variables to point the AI Factory at your existing Terraform-managed resources:

| Variable | Description |
|---|---|
| `vnetNameFull_param` | Full name of your existing VNet |
| `vnetResourceGroup_param` | Resource group of your existing VNet |
| `commonResourceGroup_param` | Existing common resource group name |
| `datalakeName_param` | Existing data lake storage account name |
| `kvNameFromCOMMON_param` | Existing common Key Vault name |
| `BYO_subnets=true` | Use your pre-existing subnets |
| `centralDnsZoneByPolicyInHub=true` | Use your existing centralised private DNS zones |
| `privDnsSubscription_param` | Subscription containing your DNS zones |
| `privDnsResourceGroup_param` | Resource group containing your DNS zones |

---

## Terraform References

The `environment_setup/aifactory/terraform/` directory contains Terraform reference configurations that can be used as a starting point for managing shared infrastructure outside the AI Factory Bicep pipeline.

---

!!! tip
    For most new deployments, the **full Bicep** approach (no BYO Terraform) is recommended — it is simpler, faster, and fully supported. Use BYO Terraform only when integrating into an existing Terraform-managed estate.
