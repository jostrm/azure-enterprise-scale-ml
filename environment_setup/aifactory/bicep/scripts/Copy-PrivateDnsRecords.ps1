# Copy Private Endpoint DNS Records Between Resource Groups
# Generic script to copy A records from source private DNS zones to target private DNS zones
# Can work within same subscription or across subscriptions

param(
    [Parameter(Mandatory = $true)]
    [string]$SourceSubscriptionId,
    
    [Parameter(Mandatory = $true)]
    [string]$TargetSubscriptionId,
    
    [Parameter(Mandatory = $true)]
    [string]$TenantId,
    
    [Parameter(Mandatory = $true)]
    [string]$SourceResourceGroup,
    
    [Parameter(Mandatory = $true)]
    [string]$TargetResourceGroup,
    
    [Parameter(Mandatory = $false)]
    [string[]]$DnsZoneNames = @(),
    
    [Parameter(Mandatory = $false)]
    [string[]]$RecordNames = @(),
    
    [Parameter(Mandatory = $false)]
    [switch]$CopyAllZones = $false,
    
    [Parameter(Mandatory = $false)]
    [switch]$WhatIf = $false,
    
    [Parameter(Mandatory = $false)]
    [switch]$OverwriteExisting,
    
    [Parameter(Mandatory = $false)]
    [int]$RecordTtl = 300,
    
    [Parameter(Mandatory = $false)]
    [switch]$Verbose = $false,
    
    [Parameter(Mandatory = $false)]
    [string]$Location = "eastus2"
)

# Default AI Factory related zones - ALL 30 zones from CmnPrivateDnsZones.bicep
$defaultZones = @(
    # Storage zones (5)
    "privatelink.blob.core.windows.net",
    "privatelink.file.core.windows.net", 
    "privatelink.dfs.core.windows.net",
    "privatelink.queue.core.windows.net",
    "privatelink.table.core.windows.net",
    
    # Container Registry (2) - including location-specific
    "privatelink.azurecr.io",
    "$Location.data.privatelink.azurecr.io",
    
    # Security & Key Management (1)
    "privatelink.vaultcore.azure.net",
    
    # AI/ML Services (4)
    "privatelink.api.azureml.ms",
    "privatelink.notebooks.azure.net",
    "privatelink.openai.azure.com",
    "privatelink.cognitiveservices.azure.com",
    
    # Data Factory (2)
    "privatelink.datafactory.azure.net",
    "privatelink.adf.azure.com",
    
    # Search & AI Services (2)
    "privatelink.search.windows.net",
    "privatelink.services.ai.azure.com",
    
    # Web & App Services (2) - including location-specific
    "privatelink.azurewebsites.net",
    "privatelink.$Location.azurecontainerapps.io",
    
    # Database Services (4)
    "privatelink.documents.azure.com",        # Cosmos DB NoSQL
    "privatelink.mongo.cosmos.azure.com",     # Cosmos DB MongoDB  
    "privatelink.postgres.database.azure.com", # PostgreSQL
    "privatelink.database.windows.net",       # SQL Database
    
    # Analytics & Big Data (1)
    "privatelink.azuredatabricks.net",
    
    # Messaging & Events (2)
    "privatelink.servicebus.windows.net",
    "privatelink.eventgrid.azure.net",
    
    # Monitoring & Management (4)
    "privatelink.monitor.azure.com",
    "privatelink.oms.opinsights.azure.com",
    "privatelink.ods.opinsights.azure.com",
    "privatelink.agentsvc.azure-automation.net",
    
    # Cache (2)
    "privatelink.redis.cache.windows.net"
    "privatelink.redis.azure.net"
    
    # Includes the separate Azure Managed Redis zone.
)

# Use provided zones or defaults
$zonesToProcess = if ($DnsZoneNames.Count -gt 0) { $DnsZoneNames } else { $defaultZones }

Write-Host "=== Copy Private DNS Records Between Resource Groups ===" -ForegroundColor Green
Write-Host "Source: $SourceResourceGroup (Subscription: $SourceSubscriptionId)" -ForegroundColor Cyan
Write-Host "Target: $TargetResourceGroup (Subscription: $TargetSubscriptionId)" -ForegroundColor Cyan
Write-Host ""

if ($WhatIf) {
    Write-Host "🔍 WHAT-IF MODE: No changes will be made" -ForegroundColor Magenta
    Write-Host ""
}

# Check authentication
try {
    $context = Get-AzContext
    if (-not $context -or $context.Tenant.Id -ne $TenantId) {
        Write-Host "Please authenticate to the correct tenant first:" -ForegroundColor Red
        Write-Host "Connect-AzAccount -TenantId $TenantId" -ForegroundColor Cyan
        exit 1
    }
    Write-Host "✓ Authenticated to tenant: $($context.Tenant.Id)" -ForegroundColor Green
} catch {
    Write-Host "Please authenticate first: Connect-AzAccount -TenantId $TenantId" -ForegroundColor Red
    exit 1
}

$recordsCopied = 0
$zonesProcessed = 0
$errors = 0
$skippedRecords = 0

# If CopyAllZones is specified, get all zones from source
if ($CopyAllZones) {
    Write-Host "🔍 Discovering all DNS zones in source resource group..." -ForegroundColor Yellow
    Set-AzContext -SubscriptionId $SourceSubscriptionId | Out-Null
    
    try {
        $allSourceZones = Get-AzPrivateDnsZone -ResourceGroupName $SourceResourceGroup
        $zonesToProcess = $allSourceZones.Name
        Write-Host "✓ Found $($zonesToProcess.Count) zones in source" -ForegroundColor Green
    } catch {
        Write-Host "✗ Error discovering source zones: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

foreach ($zoneName in $zonesToProcess) {
    Write-Host "`nProcessing zone: $zoneName" -ForegroundColor Yellow
    
    # Get records from Source zone
    Write-Host "  📖 Getting records from Source zone..." -ForegroundColor Cyan
    Set-AzContext -SubscriptionId $SourceSubscriptionId | Out-Null
    
    try {
        $sourceZone = Get-AzPrivateDnsZone -Name $zoneName -ResourceGroupName $SourceResourceGroup -ErrorAction SilentlyContinue
        if (-not $sourceZone) {
            Write-Host "  ⚠ Zone not found in Source, skipping" -ForegroundColor Yellow
            continue
        }
        
        $sourceRecords = Get-AzPrivateDnsRecordSet -Zone $sourceZone -RecordType A
        $nonSoaRecords = $sourceRecords | Where-Object { $_.Name -ne "@" }
        
        # Filter by specific record names if provided
        if ($RecordNames.Count -gt 0) {
            $nonSoaRecords = $nonSoaRecords | Where-Object { $_.Name -in $RecordNames }
        }
        
        if ($nonSoaRecords.Count -eq 0) {
            Write-Host "  ℹ No matching A records found in Source zone" -ForegroundColor Gray
            continue
        }
        
        Write-Host "  ✓ Found $($nonSoaRecords.Count) A records in Source" -ForegroundColor Green
        
        if ($Verbose) {
            foreach ($record in $nonSoaRecords) {
                $ips = $record.Records.Ipv4Address -join ", "
                Write-Host "    - $($record.Name) → $ips" -ForegroundColor Gray
            }
        }
        
    } catch {
        Write-Host "  ✗ Error reading Source zone: $($_.Exception.Message)" -ForegroundColor Red
        $errors++
        continue
    }
    
    # Check if Target zone exists
    Write-Host "  📋 Checking Target zone..." -ForegroundColor Cyan
    Set-AzContext -SubscriptionId $TargetSubscriptionId | Out-Null
    
    try {
        $targetZone = Get-AzPrivateDnsZone -Name $zoneName -ResourceGroupName $TargetResourceGroup -ErrorAction SilentlyContinue
        if (-not $targetZone) {
            Write-Host "  ⚠ Zone not found in Target, skipping" -ForegroundColor Yellow
            Write-Host "    💡 You may need to create the zone first: New-AzPrivateDnsZone -Name '$zoneName' -ResourceGroupName '$TargetResourceGroup'" -ForegroundColor White
            continue
        }
        
        $zonesProcessed++
        
    } catch {
        Write-Host "  ✗ Error accessing Target zone: $($_.Exception.Message)" -ForegroundColor Red
        $errors++
        continue
    }
    
    if ($WhatIf) {
        Write-Host "  🔍 WHAT-IF: Would copy these records to Target:" -ForegroundColor Magenta
        foreach ($record in $nonSoaRecords) {
            $ips = $record.Records.Ipv4Address -join ", "
            Write-Host "    - $($record.Name) → $ips" -ForegroundColor White
        }
        continue
    }
    
    # Copy each A record from Source to Target
    foreach ($record in $nonSoaRecords) {
        try {
            $recordName = $record.Name
            $ips = $record.Records.Ipv4Address
            
            Write-Host "    📝 Processing record: $recordName" -ForegroundColor Cyan
            
            # Check if record already exists in Target
            $existingRecord = Get-AzPrivateDnsRecordSet -Zone $targetZone -Name $recordName -RecordType A -ErrorAction SilentlyContinue
            
            if ($existingRecord -and -not $OverwriteExisting.IsPresent) {
                Write-Host "      ⚠ Record exists in Target, skipping (use -OverwriteExisting to replace)" -ForegroundColor Yellow
                $skippedRecords++
                continue
            }
            
            if ($existingRecord -and $OverwriteExisting.IsPresent) {
                Write-Host "      🔄 Record exists in Target, updating..." -ForegroundColor Yellow
                # Remove existing record
                Remove-AzPrivateDnsRecordSet -RecordSet $existingRecord -Confirm:$false | Out-Null
            }
            
            # Create new record in Target
            $newRecord = New-AzPrivateDnsRecordSet `
                -Zone $targetZone `
                -Name $recordName `
                -RecordType A `
                -Ttl $RecordTtl
            
            # Add IP addresses
            foreach ($ip in $ips) {
                Add-AzPrivateDnsRecordConfig -RecordSet $newRecord -Ipv4Address $ip | Out-Null
            }
            
            # Save the record
            Set-AzPrivateDnsRecordSet -RecordSet $newRecord | Out-Null
            
            $ipList = $ips -join ", "
            Write-Host "      ✓ Copied: $recordName → $ipList" -ForegroundColor Green
            $recordsCopied++
            
        } catch {
            Write-Host "      ✗ Failed to copy record: $($_.Exception.Message)" -ForegroundColor Red
            $errors++
        }
    }
}

# Summary
Write-Host "`n=== Summary ===" -ForegroundColor Green
Write-Host "✓ Zones processed: $zonesProcessed" -ForegroundColor Green
Write-Host "✓ Records copied: $recordsCopied" -ForegroundColor Green
if ($skippedRecords -gt 0) {
    Write-Host "⚠ Records skipped: $skippedRecords" -ForegroundColor Yellow
}
if ($errors -gt 0) {
    Write-Host "✗ Errors encountered: $errors" -ForegroundColor Red
}

if ($WhatIf) {
    Write-Host "`n🔍 This was a WHAT-IF run - no changes were made" -ForegroundColor Magenta
    Write-Host "Run without -WhatIf to actually copy the records" -ForegroundColor White
} elseif ($recordsCopied -gt 0) {
    Write-Host "`n🎉 DNS records have been copied to target zones!" -ForegroundColor Green
    Write-Host "`n=== Usage Examples ===" -ForegroundColor Magenta
    Write-Host "# Copy specific zones:" -ForegroundColor White
    Write-Host ".\Copy-PrivateDnsRecords.ps1 -SourceSubscriptionId 'sub1' -TargetSubscriptionId 'sub2' -TenantId 'tenant' -SourceResourceGroup 'rg1' -TargetResourceGroup 'rg2' -DnsZoneNames @('privatelink.blob.core.windows.net')" -ForegroundColor Gray
    Write-Host ""
    Write-Host "# Copy all zones with custom location:" -ForegroundColor White
    Write-Host ".\Copy-PrivateDnsRecords.ps1 -SourceSubscriptionId 'sub1' -TargetSubscriptionId 'sub2' -TenantId 'tenant' -SourceResourceGroup 'rg1' -TargetResourceGroup 'rg2' -Location 'westus2'" -ForegroundColor Gray
    Write-Host ""
    Write-Host "# Copy all zones from source (discover dynamically):" -ForegroundColor White
    Write-Host ".\Copy-PrivateDnsRecords.ps1 -SourceSubscriptionId 'sub1' -TargetSubscriptionId 'sub2' -TenantId 'tenant' -SourceResourceGroup 'rg1' -TargetResourceGroup 'rg2' -CopyAllZones" -ForegroundColor Gray
    Write-Host ""
    Write-Host "# Copy specific records only:" -ForegroundColor White
    Write-Host ".\Copy-PrivateDnsRecords.ps1 -SourceSubscriptionId 'sub1' -TargetSubscriptionId 'sub2' -TenantId 'tenant' -SourceResourceGroup 'rg1' -TargetResourceGroup 'rg2' -RecordNames @('myservice', 'myapi')" -ForegroundColor Gray
} else {
    Write-Host "`n⚠ No records were copied." -ForegroundColor Yellow
    Write-Host "This might indicate that:" -ForegroundColor White
    Write-Host "- The records don't exist in source zones" -ForegroundColor White
    Write-Host "- The target zones don't exist" -ForegroundColor White
    Write-Host "- The specified record names don't match" -ForegroundColor White
}

Write-Host ""