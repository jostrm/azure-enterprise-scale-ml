metadata description = 'Creates an Azure Database for PostgreSQL - Flexible Server.'
param name string
param location string
param tags object
param sku object 
param storage object
param version string
param administratorLogin string = 'aifactory-admin'
param resourceExists bool = false
@secure()
@description('Administrator login password. If not provided, a random password will be generated.')
param administratorLoginPassword string = ''
param databaseNames array = []
param allowAzureIPsFirewall bool = false
param allowAllIPsFirewall bool = true
param allowedSingleIPs array = []
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param createPrivateEndpoint bool
@description('The name of an existing keyvault, that it will be used to store secrets (connection string)' )
param keyvaultName string
param connectionStringKey string = 'aifactory-proj-postgresqlflex-con-string'
param systemAssignedIdentity bool = false // Enables system assigned managed identity on the resource
param userAssignedIdentities object = {} // Optional. The ID(s) to assign to the resource.

var identityType = systemAssignedIdentity 
  ? (!empty(userAssignedIdentities) ? 'SystemAssigned, UserAssigned' : 'SystemAssigned') 
  : (!empty(userAssignedIdentities) ? 'UserAssigned' : 'None')

var identity = identityType != 'None' ? {
  type: identityType
  userAssignedIdentities: !empty(userAssignedIdentities) ? userAssignedIdentities : {}
} : {}

var seed = uniqueString(resourceGroup().id, subscription().subscriptionId, deployment().name)
var uppercaseLetter = substring(toUpper(seed), 0, 1)
var lowercaseLetter = substring(toLower(seed), 1, 1)
var numbers = substring(seed, 2, 4)
var specialChar = '!@#$'
var randomSpecialChar = substring(specialChar, length(seed) % length(specialChar), 1)
var loginPwd = empty(administratorLoginPassword)? '${uppercaseLetter}${lowercaseLetter}${randomSpecialChar}${numbers}${guid(deployment().name)}': administratorLoginPassword

// Add error handling for empty databaseNames
var defaultDbName = 'aifdb' // Default database name
var dbNameToUse = !empty(databaseNames) ? first(databaseNames) : defaultDbName

resource flexibleServers_mypgfrelx001_name_resource 'Microsoft.DBforPostgreSQL/flexibleServers@2024-11-01-preview' = {
  name: name
  location: 'Sweden Central'
  sku: {
    name: 'Standard_B2s'
    tier: 'Burstable'
  }
  properties: {
    replica: {
      role: 'Primary'
    }
    storage: {
      iops: 120
      tier: 'P4'
      storageSizeGB: 32
      autoGrow: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    dataEncryption: {
      type: 'SystemManaged'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Enabled'
      tenantId: 'd06d9bae-d2c3-48a1-a76f-05221564d208'
    }
    version: '16'
    administratorLogin: administratorLogin
    administratorLoginPassword: loginPwd
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    maintenanceWindow: {
      customWindow: 'Disabled'
      dayOfWeek: 0
      startHour: 0
      startMinute: 0
    }
    replicationRole: 'Primary'
  }
}
resource flexibleServers_mypgfrelx001_name_4dd75919_56b3_4e7e_a265_dc96f9cd4a58 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: '4dd75919-56b3-4e7e-a265-dc96f9cd4a58'
  properties: {
    principalType: 'User'
    principalName: 'jostrm_microsoft.com#EXT#@MngEnvMCAP806050.onmicrosoft.com'
    tenantId: 'd06d9bae-d2c3-48a1-a76f-05221564d208'
  }
}

resource flexibleServers_mypgfrelx001_name_Default 'Microsoft.DBforPostgreSQL/flexibleServers/advancedThreatProtectionSettings@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'Default'
  properties: {
    state: 'Enabled'
  }
}

resource flexibleServers_mypgfrelx001_name_backup_638836138924624195 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'backup_638836138924624195'
}

resource flexibleServers_mypgfrelx001_name_allow_in_place_tablespaces 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'allow_in_place_tablespaces'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_allow_system_table_mods 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'allow_system_table_mods'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_application_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'application_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_archive_cleanup_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'archive_cleanup_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_archive_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'archive_command'
  properties: {
    value: 'BlobLogUpload.sh %f %p'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_archive_library 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'archive_library'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_archive_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'archive_mode'
  properties: {
    value: 'always'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_archive_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'archive_timeout'
  properties: {
    value: '300'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_array_nulls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'array_nulls'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_authentication_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'authentication_timeout'
  properties: {
    value: '30'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_analyze 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_analyze'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_buffers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_format 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_format'
  properties: {
    value: 'text'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_min_duration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_min_duration'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_nested_statements 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_nested_statements'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_settings 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_settings'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_timing 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_timing'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_triggers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_triggers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_verbose 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_verbose'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_log_wal 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.log_wal'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_auto_explain_sample_rate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'auto_explain.sample_rate'
  properties: {
    value: '1.0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_analyze_scale_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_analyze_scale_factor'
  properties: {
    value: '0.1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_analyze_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_analyze_threshold'
  properties: {
    value: '50'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_freeze_max_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_freeze_max_age'
  properties: {
    value: '200000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_max_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_max_workers'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_multixact_freeze_max_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_multixact_freeze_max_age'
  properties: {
    value: '400000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_naptime 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_naptime'
  properties: {
    value: '60'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_vacuum_cost_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_vacuum_cost_delay'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_vacuum_cost_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_vacuum_cost_limit'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_vacuum_insert_scale_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_vacuum_insert_scale_factor'
  properties: {
    value: '0.2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_vacuum_insert_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_vacuum_insert_threshold'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_vacuum_scale_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_vacuum_scale_factor'
  properties: {
    value: '0.2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_vacuum_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_vacuum_threshold'
  properties: {
    value: '50'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_autovacuum_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'autovacuum_work_mem'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_accepted_password_auth_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.accepted_password_auth_method'
  properties: {
    value: 'md5,scram-sha-256'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_enable_temp_tablespaces_on_local_ssd 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.enable_temp_tablespaces_on_local_ssd'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.extensions'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_migration_copy_with_binary 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.migration_copy_with_binary'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_migration_skip_analyze 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.migration_skip_analyze'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_migration_skip_extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.migration_skip_extensions'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_migration_skip_large_objects 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.migration_skip_large_objects'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_migration_skip_role_user 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.migration_skip_role_user'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_migration_table_split_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.migration_table_split_size'
  properties: {
    value: '20480'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_service_principal_id 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.service_principal_id'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_service_principal_tenant_id 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.service_principal_tenant_id'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_single_to_flex_migration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure.single_to_flex_migration'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_change_batch_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.change_batch_buffer_size'
  properties: {
    value: '16'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_change_batch_export_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.change_batch_export_timeout'
  properties: {
    value: '30'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_max_fabric_mirrors 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.max_fabric_mirrors'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_max_snapshot_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.max_snapshot_workers'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_parquet_compression 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.parquet_compression'
  properties: {
    value: 'zstd'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_snapshot_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.snapshot_buffer_size'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_cdc_snapshot_export_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_cdc.snapshot_export_timeout'
  properties: {
    value: '180'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_storage_allow_network_access 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_storage.allow_network_access'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_storage_blob_block_size_mb 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_storage.blob_block_size_mb'
  properties: {
    value: '128'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_storage_public_account_access 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_storage.public_account_access'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_backend_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'backend_flush_after'
  properties: {
    value: '256'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_backslash_quote 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'backslash_quote'
  properties: {
    value: 'safe_encoding'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_backtrace_functions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'backtrace_functions'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bgwriter_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bgwriter_delay'
  properties: {
    value: '20'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bgwriter_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bgwriter_flush_after'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bgwriter_lru_maxpages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bgwriter_lru_maxpages'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bgwriter_lru_multiplier 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bgwriter_lru_multiplier'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_block_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'block_size'
  properties: {
    value: '8192'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bonjour 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bonjour'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bonjour_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bonjour_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_bytea_output 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'bytea_output'
  properties: {
    value: 'hex'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_check_function_bodies 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'check_function_bodies'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_checkpoint_completion_target 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'checkpoint_completion_target'
  properties: {
    value: '0.9'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_checkpoint_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'checkpoint_flush_after'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_checkpoint_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'checkpoint_timeout'
  properties: {
    value: '600'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_checkpoint_warning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'checkpoint_warning'
  properties: {
    value: '30'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_client_connection_check_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'client_connection_check_interval'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_client_encoding 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'client_encoding'
  properties: {
    value: 'UTF8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_client_min_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'client_min_messages'
  properties: {
    value: 'notice'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cluster_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cluster_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_commit_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'commit_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_commit_siblings 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'commit_siblings'
  properties: {
    value: '5'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_compute_query_id 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'compute_query_id'
  properties: {
    value: 'auto'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_config_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'config_file'
  properties: {
    value: '/datadrive/pg/data/postgresql.conf'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_bucket_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.bucket_limit'
  properties: {
    value: '2000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_enable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.enable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_factor_bias 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.factor_bias'
  properties: {
    value: '0.8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_hash_entries_max 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.hash_entries_max'
  properties: {
    value: '500'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_reset_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.reset_time'
  properties: {
    value: '120'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_restore_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.restore_factor'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_connection_throttle_update_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'connection_throttle.update_time'
  properties: {
    value: '20'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_constraint_exclusion 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'constraint_exclusion'
  properties: {
    value: 'partition'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cpu_index_tuple_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cpu_index_tuple_cost'
  properties: {
    value: '0.005'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cpu_operator_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cpu_operator_cost'
  properties: {
    value: '0.0025'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cpu_tuple_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cpu_tuple_cost'
  properties: {
    value: '0.01'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cron_database_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cron.database_name'
  properties: {
    value: 'postgres'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cron_log_run 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cron.log_run'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cron_log_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cron.log_statement'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cron_max_running_jobs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cron.max_running_jobs'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_cursor_tuple_fraction 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'cursor_tuple_fraction'
  properties: {
    value: '0.1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_data_checksums 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'data_checksums'
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_data_directory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'data_directory'
  properties: {
    value: '/datadrive/pg/data'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_data_directory_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'data_directory_mode'
  properties: {
    value: '0700'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_data_sync_retry 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'data_sync_retry'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_DateStyle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'DateStyle'
  properties: {
    value: 'ISO, MDY'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_db_user_namespace 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'db_user_namespace'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_deadlock_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'deadlock_timeout'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_assertions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_assertions'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_discard_caches 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_discard_caches'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_parallel_query 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_parallel_query'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_pretty_print 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_pretty_print'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_print_parse 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_print_parse'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_print_plan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_print_plan'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_debug_print_rewritten 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'debug_print_rewritten'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_statistics_target 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_statistics_target'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_table_access_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_table_access_method'
  properties: {
    value: 'heap'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_tablespace 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_tablespace'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_text_search_config 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_text_search_config'
  properties: {
    value: 'pg_catalog.english'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_toast_compression 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_toast_compression'
  properties: {
    value: 'pglz'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_transaction_deferrable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_transaction_deferrable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_transaction_isolation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_transaction_isolation'
  properties: {
    value: 'read committed'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_default_transaction_read_only 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'default_transaction_read_only'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_dynamic_library_path 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'dynamic_library_path'
  properties: {
    value: '$libdir'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_dynamic_shared_memory_type 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'dynamic_shared_memory_type'
  properties: {
    value: 'posix'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_effective_cache_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'effective_cache_size'
  properties: {
    value: '393216'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_effective_io_concurrency 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'effective_io_concurrency'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_async_append 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_async_append'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_bitmapscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_bitmapscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_gathermerge 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_gathermerge'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_hashagg 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_hashagg'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_hashjoin 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_hashjoin'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_incremental_sort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_incremental_sort'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_indexonlyscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_indexonlyscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_indexscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_indexscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_material 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_material'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_memoize 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_memoize'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_mergejoin 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_mergejoin'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_nestloop 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_nestloop'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_parallel_append 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_parallel_append'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_parallel_hash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_parallel_hash'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_partition_pruning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_partition_pruning'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_partitionwise_aggregate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_partitionwise_aggregate'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_partitionwise_join 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_partitionwise_join'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_seqscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_seqscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_sort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_sort'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_enable_tidscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'enable_tidscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_escape_string_warning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'escape_string_warning'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_event_source 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'event_source'
  properties: {
    value: 'PostgreSQL'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_exit_on_error 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'exit_on_error'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_external_pid_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'external_pid_file'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_extra_float_digits 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'extra_float_digits'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_from_collapse_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'from_collapse_limit'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_fsync 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'fsync'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_full_page_writes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'full_page_writes'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo_effort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo_effort'
  properties: {
    value: '5'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo_generations 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo_generations'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo_pool_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo_pool_size'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo_seed 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo_seed'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo_selection_bias 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo_selection_bias'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_geqo_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'geqo_threshold'
  properties: {
    value: '12'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_gin_fuzzy_search_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'gin_fuzzy_search_limit'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_gin_pending_list_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'gin_pending_list_limit'
  properties: {
    value: '4096'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_hash_mem_multiplier 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'hash_mem_multiplier'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_hba_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'hba_file'
  properties: {
    value: '/datadrive/pg/data/pg_hba.conf'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_hot_standby 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'hot_standby'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_hot_standby_feedback 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'hot_standby_feedback'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_huge_page_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'huge_page_size'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_huge_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'huge_pages'
  properties: {
    value: 'try'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ident_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ident_file'
  properties: {
    value: '/datadrive/pg/data/pg_ident.conf'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_idle_in_transaction_session_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'idle_in_transaction_session_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_idle_session_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'idle_session_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ignore_checksum_failure 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ignore_checksum_failure'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ignore_invalid_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ignore_invalid_pages'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ignore_system_indexes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ignore_system_indexes'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_in_hot_standby 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'in_hot_standby'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_integer_datetimes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'integer_datetimes'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_intelligent_tuning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'intelligent_tuning'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_intelligent_tuning_metric_targets 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'intelligent_tuning.metric_targets'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_IntervalStyle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'IntervalStyle'
  properties: {
    value: 'postgres'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_above_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_above_cost'
  properties: {
    value: '100000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_debugging_support 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_debugging_support'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_dump_bitcode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_dump_bitcode'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_expressions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_expressions'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_inline_above_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_inline_above_cost'
  properties: {
    value: '500000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_optimize_above_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_optimize_above_cost'
  properties: {
    value: '500000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_profiling_support 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_profiling_support'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_provider 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_provider'
  properties: {
    value: 'llvmjit'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_jit_tuple_deforming 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'jit_tuple_deforming'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_join_collapse_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'join_collapse_limit'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_krb_caseins_users 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'krb_caseins_users'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_krb_server_keyfile 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'krb_server_keyfile'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_lc_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'lc_messages'
  properties: {
    value: 'en_US.utf8'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_lc_monetary 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'lc_monetary'
  properties: {
    value: 'en_US.utf-8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_lc_numeric 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'lc_numeric'
  properties: {
    value: 'en_US.utf-8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_lc_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'lc_time'
  properties: {
    value: 'en_US.utf8'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_listen_addresses 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'listen_addresses'
  properties: {
    value: '*'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_lo_compat_privileges 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'lo_compat_privileges'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_local_preload_libraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'local_preload_libraries'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_lock_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'lock_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_autovacuum_min_duration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_autovacuum_min_duration'
  properties: {
    value: '600000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_checkpoints 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_checkpoints'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_connections'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_destination 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_destination'
  properties: {
    value: 'stderr'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_directory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_directory'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_disconnections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_disconnections'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_duration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_duration'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_error_verbosity 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_error_verbosity'
  properties: {
    value: 'default'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_executor_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_executor_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_file_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_file_mode'
  properties: {
    value: '0600'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_log_filename 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_filename'
  properties: {
    value: 'postgresql-%Y-%m-%d_%H%M%S.log'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_hostname 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_hostname'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_line_prefix 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_line_prefix'
  properties: {
    value: '%t-%c-'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_lock_waits 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_lock_waits'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_min_duration_sample 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_min_duration_sample'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_min_duration_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_min_duration_statement'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_min_error_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_min_error_statement'
  properties: {
    value: 'error'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_min_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_min_messages'
  properties: {
    value: 'warning'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_parameter_max_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_parameter_max_length'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_parameter_max_length_on_error 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_parameter_max_length_on_error'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_parser_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_parser_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_planner_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_planner_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_recovery_conflict_waits 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_recovery_conflict_waits'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_replication_commands 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_replication_commands'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_rotation_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_rotation_age'
  properties: {
    value: '60'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_log_rotation_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_rotation_size'
  properties: {
    value: '102400'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_log_startup_progress_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_startup_progress_interval'
  properties: {
    value: '10000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_statement'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_statement_sample_rate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_statement_sample_rate'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_statement_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_statement_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_temp_files 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_temp_files'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_timezone 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_timezone'
  properties: {
    value: 'UTC'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_log_transaction_sample_rate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_transaction_sample_rate'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_log_truncate_on_rotation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'log_truncate_on_rotation'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_logfiles_download_enable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'logfiles.download_enable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_logfiles_retention_days 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'logfiles.retention_days'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_logging_collector 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'logging_collector'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_logical_decoding_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'logical_decoding_work_mem'
  properties: {
    value: '65536'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_maintenance_io_concurrency 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'maintenance_io_concurrency'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_maintenance_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'maintenance_work_mem'
  properties: {
    value: '157696'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_connections'
  properties: {
    value: '429'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_files_per_process 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_files_per_process'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_function_args 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_function_args'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_identifier_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_identifier_length'
  properties: {
    value: '63'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_index_keys 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_index_keys'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_locks_per_transaction 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_locks_per_transaction'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_logical_replication_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_logical_replication_workers'
  properties: {
    value: '4'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_parallel_apply_workers_per_subscription 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_parallel_apply_workers_per_subscription'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_parallel_maintenance_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_parallel_maintenance_workers'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_parallel_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_parallel_workers'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_parallel_workers_per_gather 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_parallel_workers_per_gather'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_pred_locks_per_page 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_pred_locks_per_page'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_pred_locks_per_relation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_pred_locks_per_relation'
  properties: {
    value: '-2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_pred_locks_per_transaction 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_pred_locks_per_transaction'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_prepared_transactions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_prepared_transactions'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_replication_slots 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_replication_slots'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_slot_wal_keep_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_slot_wal_keep_size'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_stack_depth 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_stack_depth'
  properties: {
    value: '2048'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_max_standby_archive_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_standby_archive_delay'
  properties: {
    value: '30000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_standby_streaming_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_standby_streaming_delay'
  properties: {
    value: '30000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_sync_workers_per_subscription 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_sync_workers_per_subscription'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_wal_senders 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_wal_senders'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_wal_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_wal_size'
  properties: {
    value: '2048'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_max_worker_processes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'max_worker_processes'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_metrics_autovacuum_diagnostics 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'metrics.autovacuum_diagnostics'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_metrics_collector_database_activity 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'metrics.collector_database_activity'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_metrics_pgbouncer_diagnostics 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'metrics.pgbouncer_diagnostics'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_min_dynamic_shared_memory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'min_dynamic_shared_memory'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_min_parallel_index_scan_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'min_parallel_index_scan_size'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_min_parallel_table_scan_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'min_parallel_table_scan_size'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_min_wal_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'min_wal_size'
  properties: {
    value: '80'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_parallel_leader_participation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'parallel_leader_participation'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_parallel_setup_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'parallel_setup_cost'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_parallel_tuple_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'parallel_tuple_cost'
  properties: {
    value: '0.1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_password_encryption 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'password_encryption'
  properties: {
    value: 'scram-sha-256'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_partman_bgw_analyze 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_partman_bgw.analyze'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_partman_bgw_dbname 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_partman_bgw.dbname'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_partman_bgw_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_partman_bgw.interval'
  properties: {
    value: '3600'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_partman_bgw_jobmon 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_partman_bgw.jobmon'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_partman_bgw_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_partman_bgw.role'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_interval_length_minutes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.interval_length_minutes'
  properties: {
    value: '15'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_is_enabled_fs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.is_enabled_fs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_max_plan_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.max_plan_size'
  properties: {
    value: '7500'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_max_query_text_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.max_query_text_length'
  properties: {
    value: '6000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_parameters_capture_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.parameters_capture_mode'
  properties: {
    value: 'capture_parameterless_only'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_query_capture_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.query_capture_mode'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_retention_period_in_days 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.retention_period_in_days'
  properties: {
    value: '7'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_store_query_plans 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.store_query_plans'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_qs_track_utility 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_qs.track_utility'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_stat_statements_max 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_stat_statements.max'
  properties: {
    value: '5000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_stat_statements_save 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_stat_statements.save'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_stat_statements_track 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_stat_statements.track'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pg_stat_statements_track_utility 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pg_stat_statements.track_utility'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log_catalog 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log_catalog'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log_client 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log_client'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log_parameter 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log_parameter'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log_relation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log_relation'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_log_statement_once 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.log_statement_once'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgaudit_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgaudit.role'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pglogical_batch_inserts 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pglogical.batch_inserts'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pglogical_conflict_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pglogical.conflict_log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pglogical_conflict_resolution 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pglogical.conflict_resolution'
  properties: {
    value: 'apply_remote'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pglogical_use_spi 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pglogical.use_spi'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgms_stats_is_enabled_fs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgms_stats.is_enabled_fs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgms_wait_sampling_history_period 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgms_wait_sampling.history_period'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgms_wait_sampling_is_enabled_fs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgms_wait_sampling.is_enabled_fs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pgms_wait_sampling_query_capture_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pgms_wait_sampling.query_capture_mode'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_plan_cache_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'plan_cache_mode'
  properties: {
    value: 'auto'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_port 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'port'
  properties: {
    value: '5432'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_post_auth_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'post_auth_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_postgis_gdal_enabled_drivers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'postgis.gdal_enabled_drivers'
  properties: {
    value: 'DISABLE_ALL'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_pre_auth_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'pre_auth_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_primary_conninfo 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'primary_conninfo'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_primary_slot_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'primary_slot_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_quote_all_identifiers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'quote_all_identifiers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_random_page_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'random_page_cost'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_end_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_end_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_init_sync_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_init_sync_method'
  properties: {
    value: 'fsync'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_min_apply_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_min_apply_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_prefetch 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_prefetch'
  properties: {
    value: 'try'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_action 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_action'
  properties: {
    value: 'pause'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_inclusive 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_inclusive'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_lsn 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_lsn'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_time'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_timeline 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_timeline'
  properties: {
    value: 'latest'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recovery_target_xid 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recovery_target_xid'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_recursive_worktable_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'recursive_worktable_factor'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_remove_temp_files_after_crash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'remove_temp_files_after_crash'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_require_secure_transport 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'require_secure_transport'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_reserved_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'reserved_connections'
  properties: {
    value: '5'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_restart_after_crash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'restart_after_crash'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_restore_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'restore_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_row_security 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'row_security'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_search_path 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'search_path'
  properties: {
    value: '"$user", public'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_segment_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'segment_size'
  properties: {
    value: '131072'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_seq_page_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'seq_page_cost'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_server_encoding 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'server_encoding'
  properties: {
    value: 'UTF8'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_server_version 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'server_version'
  properties: {
    value: '16.8'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_server_version_num 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'server_version_num'
  properties: {
    value: '160008'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_session_preload_libraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'session_preload_libraries'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_session_replication_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'session_replication_role'
  properties: {
    value: 'origin'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_shared_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'shared_buffers'
  properties: {
    value: '131072'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_shared_memory_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'shared_memory_size'
  properties: {
    value: '1106'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_shared_memory_size_in_huge_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'shared_memory_size_in_huge_pages'
  properties: {
    value: '553'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_shared_memory_type 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'shared_memory_type'
  properties: {
    value: 'mmap'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_shared_preload_libraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'shared_preload_libraries'
  properties: {
    value: 'pg_cron,pg_stat_statements'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl'
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_ca_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_ca_file'
  properties: {
    value: '/datadrive/certs/ca.pem'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_cert_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_cert_file'
  properties: {
    value: '/datadrive/certs/cert.pem'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_ciphers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_ciphers'
  properties: {
    value: 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_crl_dir 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_crl_dir'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_crl_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_crl_file'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_dh_params_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_dh_params_file'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_ecdh_curve 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_ecdh_curve'
  properties: {
    value: 'prime256v1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_key_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_key_file'
  properties: {
    value: '/datadrive/certs/key.pem'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_library 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_library'
  properties: {
    value: 'OpenSSL'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_max_protocol_version 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_max_protocol_version'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_min_protocol_version 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_min_protocol_version'
  properties: {
    value: 'TLSv1.2'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_passphrase_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_passphrase_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_passphrase_command_supports_reload 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_passphrase_command_supports_reload'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_ssl_prefer_server_ciphers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'ssl_prefer_server_ciphers'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_standard_conforming_strings 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'standard_conforming_strings'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_statement_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'statement_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_stats_fetch_consistency 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'stats_fetch_consistency'
  properties: {
    value: 'cache'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_superuser_reserved_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'superuser_reserved_connections'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_synchronize_seqscans 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'synchronize_seqscans'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_synchronous_commit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'synchronous_commit'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_synchronous_standby_names 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'synchronous_standby_names'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_syslog_facility 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'syslog_facility'
  properties: {
    value: 'local0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_syslog_ident 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'syslog_ident'
  properties: {
    value: 'postgres'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_syslog_sequence_numbers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'syslog_sequence_numbers'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_syslog_split_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'syslog_split_messages'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_tcp_keepalives_count 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'tcp_keepalives_count'
  properties: {
    value: '9'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_tcp_keepalives_idle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'tcp_keepalives_idle'
  properties: {
    value: '120'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_tcp_keepalives_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'tcp_keepalives_interval'
  properties: {
    value: '30'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_tcp_user_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'tcp_user_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_temp_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'temp_buffers'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_temp_file_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'temp_file_limit'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_temp_tablespaces 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'temp_tablespaces'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_TimeZone 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'TimeZone'
  properties: {
    value: 'UTC'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_timezone_abbreviations 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'timezone_abbreviations'
  properties: {
    value: 'Default'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_trace_notify 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'trace_notify'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_trace_recovery_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'trace_recovery_messages'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_trace_sort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'trace_sort'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_activities 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_activities'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_activity_query_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_activity_query_size'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_commit_timestamp 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_commit_timestamp'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_counts 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_counts'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_functions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_functions'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_io_timing 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_io_timing'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_track_wal_io_timing 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'track_wal_io_timing'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_transaction_deferrable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'transaction_deferrable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_transaction_isolation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'transaction_isolation'
  properties: {
    value: 'read committed'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_transaction_read_only 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'transaction_read_only'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_transform_null_equals 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'transform_null_equals'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_unix_socket_directories 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'unix_socket_directories'
  properties: {
    value: '/tmp,/tmp/tuning_sockets'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_unix_socket_group 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'unix_socket_group'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_unix_socket_permissions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'unix_socket_permissions'
  properties: {
    value: '0777'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_update_process_title 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'update_process_title'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_buffer_usage_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_buffer_usage_limit'
  properties: {
    value: '256'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_cost_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_cost_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_cost_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_cost_limit'
  properties: {
    value: '200'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_cost_page_dirty 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_cost_page_dirty'
  properties: {
    value: '20'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_cost_page_hit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_cost_page_hit'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_cost_page_miss 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_cost_page_miss'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_failsafe_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_failsafe_age'
  properties: {
    value: '1600000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_freeze_min_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_freeze_min_age'
  properties: {
    value: '50000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_freeze_table_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_freeze_table_age'
  properties: {
    value: '150000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_multixact_failsafe_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_multixact_failsafe_age'
  properties: {
    value: '1600000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_multixact_freeze_min_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_multixact_freeze_min_age'
  properties: {
    value: '5000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_vacuum_multixact_freeze_table_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'vacuum_multixact_freeze_table_age'
  properties: {
    value: '150000000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_block_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_block_size'
  properties: {
    value: '8192'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_buffers'
  properties: {
    value: '2048'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_compression 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_compression'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_consistency_checking 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_consistency_checking'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_decode_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_decode_buffer_size'
  properties: {
    value: '524288'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_init_zero 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_init_zero'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_keep_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_keep_size'
  properties: {
    value: '400'
    source: 'user-override'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_level'
  properties: {
    value: 'replica'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_log_hints 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_log_hints'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_receiver_create_temp_slot 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_receiver_create_temp_slot'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_receiver_status_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_receiver_status_interval'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_receiver_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_receiver_timeout'
  properties: {
    value: '60000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_recycle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_recycle'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_retrieve_retry_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_retrieve_retry_interval'
  properties: {
    value: '5000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_segment_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_segment_size'
  properties: {
    value: '16777216'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_sender_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_sender_timeout'
  properties: {
    value: '60000'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_skip_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_skip_threshold'
  properties: {
    value: '2048'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_sync_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_sync_method'
  properties: {
    value: 'fdatasync'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_writer_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_writer_delay'
  properties: {
    value: '200'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_wal_writer_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'wal_writer_flush_after'
  properties: {
    value: '128'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'work_mem'
  properties: {
    value: '4096'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_xmlbinary 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'xmlbinary'
  properties: {
    value: 'base64'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_xmloption 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'xmloption'
  properties: {
    value: 'content'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_zero_damaged_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'zero_damaged_pages'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_maintenance 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_maintenance'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_mypgfrelx001_name_azure_sys 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'azure_sys'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_mypgfrelx001_name_postgres 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'postgres'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_mypgfrelx001_name_AllowAll_2025_5_23_18_6_32 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'AllowAll_2025-5-23_18-6-32'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '255.255.255.255'
  }
}

resource flexibleServers_mypgfrelx001_name_AllowAllAzureServicesAndResourcesWithinAzureIps_2025_5_23_18_8_9 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps_2025-5-23_18-8-9'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}
/*
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
 location: location
  tags: tags
  name: name
  identity: identity
  sku: sku
  properties: {
    version: version
    administratorLogin: administratorLogin
    administratorLoginPassword: loginPwd
    storage: storage
    highAvailability: {
      mode: 'Disabled'
    }
  }

  resource database 'databases' = [for name in databaseNames:{
    name: name
  }]

  resource firewall_all 'firewallRules' = if (allowAllIPsFirewall) {
    name: 'allow-all-IPs'
    properties: {
      startIpAddress: '0.0.0.0'
      endIpAddress: '255.255.255.255'
    }
  }

  resource firewall_azure 'firewallRules' = if (allowAzureIPsFirewall) {
    name: 'allow-all-azure-internal-IPs'
    properties: {
      startIpAddress: '0.0.0.0'
      endIpAddress: '0.0.0.0'
    }
  }

  resource firewall_single 'firewallRules' = [for ip in allowedSingleIPs: {
    name: 'allow-single-${replace(ip, '.', '')}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
  }]
}

*/

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}

resource pendPostgresServer 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpoint) {
  name: 'pend-postgreSQLFlexibleServer-${name}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-postgreSQLFlexibleServer-${name}'
        properties: {
          privateLinkServiceId: flexibleServers_mypgfrelx001_name_resource.id
          groupIds: [
            'flexibleServers'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

resource pgflexConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: connectionStringKey
  properties: {
    value: 'Server=${flexibleServers_mypgfrelx001_name_resource.properties.fullyQualifiedDomainName};Database=${dbNameToUse};Port=5432;User Id=${administratorLogin};Password=${loginPwd};Ssl Mode=Require;'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

output POSTGRES_DOMAIN_NAME string = flexibleServers_mypgfrelx001_name_resource.properties.fullyQualifiedDomainName
output name string = flexibleServers_mypgfrelx001_name_resource.name
output dnsConfig array = [
  {
    name: createPrivateEndpoint? flexibleServers_mypgfrelx001_name_resource.name: ''
    type: 'postgres'
    id: createPrivateEndpoint? flexibleServers_mypgfrelx001_name_resource.id: ''
  }
]
