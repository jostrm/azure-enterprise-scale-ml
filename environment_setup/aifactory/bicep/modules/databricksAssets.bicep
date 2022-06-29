// https://github.com/lordlinus/databricks-all-in-one-bicep-template
param location string
param force_update string = utcNow()
param identity string
param akv_id string
param akv_uri string
param adb_pat_lifetime string = '3600'
param adb_workspace_url string
param adb_workspace_id string
param adb_secret_scope_name string
param adb_cluster_name string = 'small-esmlprj000-dev-azureml-rt-7.3'
param adb_spark_version string = '7.3.x-scala2.12' //  '7.3.x-scala2.12' = 7.3 LTS (includes Apache Spark 3.0.1, Scala 2.12)
param adb_node_type string = 'Standard_D3_v2'
param adb_num_worker string = '3'
param adb_auto_terminate_min string = '30'
param LogAWkspId string
param LogAWkspKey string
param storageKey string
param evenHubKey string
param esml_pypi_lib1_package string = 'azureml-sdk[databricks]'
param esml_maven_lib1_coord string = 'HyukjinKwon:spark-xml:0.1.1-s_2.10'

// #secrets/createScope  | scope-esmlproject-kv | AllUsers |
// kv-secrets: 
// esml-tenant-id
// esml-subscription-id
// esml-project-sp-id
// esml-project-sp-secret

resource createAdbPATToken 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'createAdbPATToken'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity}': {}
    }
  }
  properties: {
    azCliVersion: '2.26.0'
    timeout: 'PT5M'
    cleanupPreference: 'OnExpiration'
    retentionInterval: 'PT1H'
    environmentVariables: [
      {
        name: 'ADB_WORKSPACE_URL'
        value: adb_workspace_url
      }
      {
        name: 'ADB_WORKSPACE_ID'
        value: adb_workspace_id
      }
      {
        name: 'PAT_LIFETIME'
        value: adb_pat_lifetime
      }
    ]
    scriptContent: loadTextContent('../scripts/databricks/deployment/create_pat.sh')
  }
}

resource secretScopeLink 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'secretScopeLink'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity}': {}
    }
  }
  properties: {
    azCliVersion: '2.26.0'
    timeout: 'PT1H'
    cleanupPreference: 'OnExpiration'
    retentionInterval: 'PT1H'
    environmentVariables: [
      {
        name: 'ADB_WORKSPACE_URL'
        value: adb_workspace_url
      }
      {
        name: 'ADB_WORKSPACE_ID'
        value: adb_workspace_id
      }
      {
        name: 'ADB_SECRET_SCOPE_NAME'
        value: adb_secret_scope_name
      }
      {
        name: 'AKV_ID'
        value: akv_id
      }
      {
        name: 'AKV_URI'
        value: akv_uri
      }
      {
        name: 'ADB_LOG_WKSP_ID'
        value: LogAWkspId
      }
      {
        name: 'ADB_LOG_WKSP_KEY'
        value: LogAWkspKey
      }
      {
        name: 'STORAGE_ACCESS_KEY'
        value: storageKey
      }
      {
        name: 'EVENT_HUB_KEY'
        value: evenHubKey
      }
      {
        name: 'ADB_PAT_TOKEN'
        value: createAdbPATToken.properties.outputs.token_value
      }
    ]
    scriptContent: loadTextContent('../scripts/databricks/deployment/create_pat.sh')
  }
  dependsOn: [
    createAdbPATToken
  ]
}

resource uploadFilesToAdb 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'uploadFilesToAdb'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity}': {}
    }
  }
  properties: {
    azCliVersion: '2.26.0'
    timeout: 'PT5M'
    cleanupPreference: 'OnExpiration'
    retentionInterval: 'PT1H'
    environmentVariables: [
      {
        name: 'ADB_WORKSPACE_URL'
        value: adb_workspace_url
      }
      {
        name: 'ADB_WORKSPACE_ID'
        value: adb_workspace_id
      }
    ]
    scriptContent: loadTextContent('../scripts/databricks/deployment/create_pat.sh')
  }
}

resource createAdbCluster 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'createAdbCluster'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity}': {}
    }
  }
  properties: {
    azCliVersion: '2.26.0'
    timeout: 'PT5M'
    retentionInterval: 'PT1H'
    cleanupPreference: 'OnExpiration'
    forceUpdateTag: force_update
    environmentVariables: [
      {
        name: 'ADB_WORKSPACE_URL'
        value: adb_workspace_url
      }
      {
        name: 'ADB_WORKSPACE_ID'
        value: adb_workspace_id
      }
      {
        name: 'ADB_SECRET_SCOPE_NAME'
        value: adb_secret_scope_name
      }
      {
        name: 'DATABRICKS_CLUSTER_NAME'
        value: adb_cluster_name
      }
      {
        name: 'DATABRICKS_SPARK_VERSION'
        value: adb_spark_version
      }
      {
        name: 'DATABRICKS_NODE_TYPE'
        value: adb_node_type
      }
      {
        name: 'DATABRICKS_NUM_WORKERS'
        value: adb_num_worker
      }
      {
        name: 'DATABRICKS_AUTO_TERMINATE_MINUTES'
        value: adb_auto_terminate_min
      }
    ]
    scriptContent: loadTextContent('../scripts/databricks/deployment/create_pat.sh')
  }
  dependsOn: [
    secretScopeLink
    uploadFilesToAdb
  ]
}

resource configAdbCluster 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'configAdbCluster'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity}': {}
    }
  }
  properties: {
    azCliVersion: '2.26.0'
    timeout: 'PT5M'
    retentionInterval: 'PT1H'
    cleanupPreference: 'OnExpiration'
    forceUpdateTag: force_update
    environmentVariables: [
      {
        name: 'ADB_WORKSPACE_URL'
        value: adb_workspace_url
      }
      {
        name: 'ADB_WORKSPACE_ID'
        value: adb_workspace_id
      }
      {
        name: 'ADB_CLUSTER_ID'
        value: createAdbCluster.id
      }
    ]
    scriptContent: loadTextContent('../scripts/databricks/deployment/create_pat.sh')
  }
}

output patOutput object = createAdbPATToken.properties
output adbCluster object = createAdbCluster.properties
