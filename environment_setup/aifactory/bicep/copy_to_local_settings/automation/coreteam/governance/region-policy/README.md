# ESAF region policy

Azure Policy kit that keeps a subscription's resources in approved regions:

| Resource | Allowed regions (defaults) |
|---|---|
| Azure AI Search (`Microsoft.Search/searchServices`) | Sweden Central, France Central, Italy North |
| Every other regional resource type | Sweden Central |
| Resource groups | Sweden Central (turn off with `-RestrictResourceGroupLocation $false`) |
| `global` resources (Private DNS zones, Front Door, ...) | not restricted |

The template copy (`01-aif-copy-aifactory-templates.sh`, step "Automation") copies this folder to
`aifactory/automation/coreteam/governance/region-policy/` in your consumer repo. Nothing here holds a
subscription or tenant ID: you pass your own.

## What it creates

| Object | Name | Purpose |
|---|---|---|
| Policy definition (Indexed) | `esaf-allowed-locations-except-types` | All regional types except the multi-region ones: baseline regions only |
| Policy definition (Indexed) | `esaf-allowed-locations-for-types` | The multi-region types (AI Search): their own region list |
| Policy definition (All) | `esaf-allowed-locations-resource-groups` | Resource groups: baseline regions only |
| Policy set (initiative) | `esaf-region-policy` | Wires the three together with one parameter set |
| Assignment | `esaf-region-policy` | Applies the set to the subscription (or one resource group) |

The rules live only in [`policies/`](policies/). Every object gets `metadata.createdBy = "esaf-region-policy"`;
the removal script deletes only objects with that marker.

## Use

Requirements: PowerShell 7, Azure CLI, a login (`az login --tenant <tenant-guid>`) with **Owner** or
**Resource Policy Contributor** on the subscription (on the management group too with `-ManagementGroupId`).

```powershell
# 1) Your settings (once): copy the example and fill in tenant and subscription
Copy-Item ./region-policy.settings.example.psd1 ./region-policy.settings.psd1
$s = Import-PowerShellDataFile ./region-policy.settings.psd1

# 2) Roll out in audit mode first: shows what would be denied, denies nothing
./New-EsafRegionPolicy.ps1 @s -EnforcementMode DoNotEnforce
az policy state trigger-scan --subscription $s.SubscriptionId

# 3) Enforce
./New-EsafRegionPolicy.ps1 @s

# Remove everything it created (preview first)
./Remove-EsafRegionPolicy.ps1 @s -WhatIf
./Remove-EsafRegionPolicy.ps1 @s -Force
```

Parameters of `New-EsafRegionPolicy.ps1` (all but the first two have defaults):

| Parameter | Default | Notes |
|---|---|---|
| `-TenantId`, `-SubscriptionId` | required | The script checks that the az login reaches the subscription in this tenant before it writes |
| `-BaselineLocations` | `swedencentral` | |
| `-MultiRegionResourceTypes` | `Microsoft.Search/searchServices` | Add types here (for example `Microsoft.CognitiveServices/accounts`) to give them the multi-region list |
| `-MultiRegionLocations` | `swedencentral, francecentral, italynorth` | Comma-separated strings work too |
| `-RestrictResourceGroupLocation` | `$true` | |
| `-EnforcementMode` | `Default` (deny) | `DoNotEnforce` = audit only |
| `-Effect` | `Deny` | `Audit` or `Disabled` |
| `-ManagementGroupId` | none | Stores the definitions and the set at the management group for reuse |
| `-AssignmentScope` | the subscription | A resource group ID limits the policy to that group |
| `-AssignmentName` | `esaf-region-policy` | Max 24 characters (management-group limit) |

Running `New-EsafRegionPolicy.ps1` again updates everything in place. It refuses to overwrite an object
with the same name that it did not create. Both scripts support `-WhatIf`.

## Before you enforce

- A deny policy also blocks **updates** of existing resources outside the allowed regions: their next
  redeploy fails. Run in `DoNotEnforce` first and check the non-compliant list.
- Don't enforce while a factory deployment that uses other regions is running on the subscription.
- Azure AI Search in **Italy North has no AI enrichment (skillsets)**; Sweden Central and France Central do
  ([regions](https://learn.microsoft.com/azure/search/search-region-support#azure-public-regions)).
- A new assignment can take a while to start denying.

## Tests

Offline contract tests (rule matrix on the real JSON, scripts run against a stand-in `az`):
`environment_setup/unit-tests/test-bicep/unit/test_region_policy.py` in the accelerator.
