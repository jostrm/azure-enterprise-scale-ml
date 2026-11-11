# Copy to region-policy.settings.psd1 in your consumer repo and fill in your own values.
# Both scripts accept every key below, so one file serves create and remove:
#   $s = Import-PowerShellDataFile ./region-policy.settings.psd1
#   ./New-EsafRegionPolicy.ps1 @s -EnforcementMode DoNotEnforce
#   ./Remove-EsafRegionPolicy.ps1 @s -WhatIf
@{
    TenantId          = '<tenant-guid>'
    SubscriptionId    = '<subscription-guid>'
    # ManagementGroupId = '<management-group-id>'   # store definitions at a management group instead
    # AssignmentScope   = '/subscriptions/<subscription-guid>/resourceGroups/<rg>'   # limit to one resource group
    # AssignmentName    = 'esaf-region-policy'
}
