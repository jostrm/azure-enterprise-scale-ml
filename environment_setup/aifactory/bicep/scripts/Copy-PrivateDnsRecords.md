# Copy-PrivateDnsRecords.ps1

A generic PowerShell script to copy A records from private DNS zones in one resource group to private DNS zones in another resource group. This script can work within the same subscription or across different subscriptions.

## Features

- ✅ Copy DNS records between different subscriptions
- ✅ Copy DNS records within the same subscription
- ✅ Copy specific DNS zones or all zones
- ✅ Copy specific records by name
- ✅ What-if mode for testing
- ✅ Overwrite existing records or skip them
- ✅ Comprehensive error handling and logging
- ✅ Verbose output option

## Parameters

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `SourceSubscriptionId` | string | Azure subscription ID containing the source DNS zones |
| `TargetSubscriptionId` | string | Azure subscription ID containing the target DNS zones |
| `TenantId` | string | Azure tenant ID |
| `SourceResourceGroup` | string | Resource group name containing source DNS zones |
| `TargetResourceGroup` | string | Resource group name containing target DNS zones |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `DnsZoneNames` | string[] | Default AI zones | Specific DNS zone names to process |
| `RecordNames` | string[] | All records | Specific record names to copy |
| `CopyAllZones` | switch | false | Copy all zones found in source resource group |
| `WhatIf` | switch | false | Preview changes without making them |
| `OverwriteExisting` | switch | false | Overwrite existing records in target |
| `RecordTtl` | int | 300 | TTL value for new records |
| `Verbose` | switch | false | Show detailed record information |

## Default DNS Zones

If no specific zones are provided, the script processes these common Azure private DNS zones:

- `privatelink.cognitiveservices.azure.com`
- `privatelink.blob.core.windows.net`
- `privatelink.search.windows.net`
- `privatelink.openai.azure.com`
- `privatelink.vaultcore.azure.net`
- `privatelink.services.ai.azure.com`
- `privatelink.api.azureml.ms`
- `privatelink.azurewebsites.net`
- `privatelink.azurecr.io`
- `privatelink.documents.azure.com`
- `privatelink.postgres.database.azure.com`
- `privatelink.mysql.database.azure.com`
- `privatelink.redis.cache.windows.net`

## Usage Examples

### 1. Basic Usage - Copy Default AI Factory Zones

```powershell
.\Copy-PrivateDnsRecords.ps1 `
    -SourceSubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
    -TargetSubscriptionId "5cd131eb-5379-4eb7-beee-996ec20f02b8" `
    -TenantId "d06d9bae-d2c3-48a1-a76f-05221564d208" `
    -SourceResourceGroup "mrvel-1-esml-common-eus2-dev-010" `
    -TargetResourceGroup "platform-connectivity"
```

### 2. What-if Mode - Preview Changes

```powershell
.\Copy-PrivateDnsRecords.ps1 `
    -SourceSubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
    -TargetSubscriptionId "5cd131eb-5379-4eb7-beee-996ec20f02b8" `
    -TenantId "d06d9bae-d2c3-48a1-a76f-05221564d208" `
    -SourceResourceGroup "mrvel-1-esml-common-eus2-dev-010" `
    -TargetResourceGroup "platform-connectivity" `
    -WhatIf
```

### 3. Copy Specific DNS Zones

```powershell
.\Copy-PrivateDnsRecords.ps1 `
    -SourceSubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
    -TargetSubscriptionId "5cd131eb-5379-4eb7-beee-996ec20f02b8" `
    -TenantId "d06d9bae-d2c3-48a1-a76f-05221564d208" `
    -SourceResourceGroup "mrvel-1-esml-common-eus2-dev-010" `
    -TargetResourceGroup "platform-connectivity" `
    -DnsZoneNames @("privatelink.blob.core.windows.net", "privatelink.openai.azure.com")
```

### 4. Copy All Zones from Source

```powershell
.\Copy-PrivateDnsRecords.ps1 `
    -SourceSubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
    -TargetSubscriptionId "5cd131eb-5379-4eb7-beee-996ec20f02b8" `
    -TenantId "d06d9bae-d2c3-48a1-a76f-05221564d208" `
    -SourceResourceGroup "mrvel-1-esml-common-eus2-dev-010" `
    -TargetResourceGroup "platform-connectivity" `
    -CopyAllZones
```

### 5. Copy Specific Records with Overwrite

```powershell
.\Copy-PrivateDnsRecords.ps1 `
    -SourceSubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
    -TargetSubscriptionId "5cd131eb-5379-4eb7-beee-996ec20f02b8" `
    -TenantId "d06d9bae-d2c3-48a1-a76f-05221564d208" `
    -SourceResourceGroup "mrvel-1-esml-common-eus2-dev-010" `
    -TargetResourceGroup "platform-connectivity" `
    -RecordNames @("myservice", "myapi") `
    -OverwriteExisting
```

### 6. Verbose Output for Debugging

```powershell
.\Copy-PrivateDnsRecords.ps1 `
    -SourceSubscriptionId "612e830e-b795-424e-ba5d-cd0a5dadecf4" `
    -TargetSubscriptionId "5cd131eb-5379-4eb7-beee-996ec20f02b8" `
    -TenantId "d06d9bae-d2c3-48a1-a76f-05221564d208" `
    -SourceResourceGroup "mrvel-1-esml-common-eus2-dev-010" `
    -TargetResourceGroup "platform-connectivity" `
    -Verbose
```

## Prerequisites

1. **PowerShell Az Module**: Install the Azure PowerShell module
   ```powershell
   Install-Module -Name Az -Repository PSGallery -Force
   ```

2. **Authentication**: Connect to Azure with appropriate permissions
   ```powershell
   Connect-AzAccount -TenantId "your-tenant-id"
   ```

3. **Permissions**: The account must have:
   - Reader permissions on source subscription/resource group
   - Contributor permissions on target subscription/resource group
   - DNS Zone Contributor role on both source and target DNS zones

## Error Handling

The script includes comprehensive error handling:
- ✅ Authentication validation
- ✅ Subscription and resource group validation
- ✅ DNS zone existence checks
- ✅ Record creation/update error handling
- ✅ Detailed error reporting in summary

## Output

The script provides:
- Real-time progress indicators
- Color-coded status messages
- Comprehensive summary with counts
- Usage examples for reference
- Troubleshooting hints

## Best Practices

1. **Always test first**: Use `-WhatIf` to preview changes
2. **Specific zones**: Specify `-DnsZoneNames` for better performance
3. **Check permissions**: Ensure proper RBAC before running
4. **Monitor output**: Watch for errors and warnings
5. **Backup strategy**: Consider backing up target zones before major changes

## Troubleshooting

### Common Issues

1. **Authentication Errors**
   - Ensure you're connected to the correct tenant
   - Verify subscription access

2. **Zone Not Found**
   - Check resource group names
   - Verify DNS zones exist in source
   - Ensure target zones are created

3. **Permission Denied**
   - Verify RBAC permissions
   - Check subscription access

4. **Records Skipped**
   - Use `-OverwriteExisting` to replace existing records
   - Check if specific record names match

## Original Script Location

This generic script was created from:
`environment_setup\aifactory\bicep\debug\azure_vpn\12-copy-dns-records-spoke-to-hub.ps1`

The original script was specific to copying from "mrvel-1-esml-common-eus2-dev-010" to "platform-connectivity" resource groups. This generic version allows copying between any resource groups with full parameter control.