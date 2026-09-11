targetScope = 'resourceGroup'

@description('An existing Data Factory. This template deploys children only.')
param factoryName string

@description('Existing self-hosted IR with DNS/network access to Blob, ARM and optional Databricks endpoints.')
param integrationRuntimeName string

@description('Storage Blob HTTPS endpoint, not a dfs endpoint.')
param sourceBlobEndpoint string
param sinkBlobEndpoint string

@description('Existing ADF credential name, for example ls_cred_project_uami. Empty uses factory system identity.')
param sourceCredentialName string = ''
param sinkCredentialName string = ''

@description('Optional existing Databricks linked service with supported authentication and private routing.')
param databricksLinkedServiceName string = ''

@description('Prefix isolates these children from other installed project templates.')
param namePrefix string = 'ml_factory'

resource factory 'Microsoft.DataFactory/factories@2018-06-01' existing = {
  name: factoryName
}

var ir = {
  referenceName: integrationRuntimeName
  type: 'IntegrationRuntimeReference'
}
var activityPolicy = {
  timeout: '0.02:00:00'
  retry: 0
  retryIntervalInSeconds: 30
  secureInput: true
  secureOutput: true
}

resource sourceStorage 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = {
  parent: factory
  name: '${namePrefix}_blob_source'
  properties: {
    type: 'AzureBlobStorage'
    connectVia: ir
    typeProperties: union({
      serviceEndpoint: sourceBlobEndpoint
      accountKind: 'StorageV2'
    }, empty(sourceCredentialName) ? {} : {
      credential: {
        referenceName: sourceCredentialName
        type: 'CredentialReference'
      }
    })
  }
}

resource sinkStorage 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = {
  parent: factory
  name: '${namePrefix}_blob_sink'
  properties: {
    type: 'AzureBlobStorage'
    connectVia: ir
    typeProperties: union({
      serviceEndpoint: sinkBlobEndpoint
      accountKind: 'StorageV2'
    }, empty(sinkCredentialName) ? {} : {
      credential: {
        referenceName: sinkCredentialName
        type: 'CredentialReference'
      }
    })
  }
}

var datasetParameters = {
  container: { type: 'String' }
  folder: { type: 'String' }
}
var binaryProperties = {
  location: {
    type: 'AzureBlobStorageLocation'
    container: { value: '@dataset().container', type: 'Expression' }
    folderPath: { value: '@dataset().folder', type: 'Expression' }
  }
}

resource sourceDataset 'Microsoft.DataFactory/factories/datasets@2018-06-01' = {
  parent: factory
  name: '${namePrefix}_source'
  properties: {
    type: 'Binary'
    parameters: datasetParameters
    linkedServiceName: { referenceName: sourceStorage.name, type: 'LinkedServiceReference' }
    typeProperties: binaryProperties
  }
}

resource sinkDataset 'Microsoft.DataFactory/factories/datasets@2018-06-01' = {
  parent: factory
  name: '${namePrefix}_sink'
  properties: {
    type: 'Binary'
    parameters: datasetParameters
    linkedServiceName: { referenceName: sinkStorage.name, type: 'LinkedServiceReference' }
    typeProperties: binaryProperties
  }
}

var copyInputs = [{
  referenceName: sourceDataset.name
  type: 'DatasetReference'
  parameters: {
    container: { value: '@pipeline().parameters.sourceContainer', type: 'Expression' }
    folder: { value: '@pipeline().parameters.sourceFolder', type: 'Expression' }
  }
}]
var copyOutputs = [{
  referenceName: sinkDataset.name
  type: 'DatasetReference'
  parameters: {
    container: { value: '@pipeline().parameters.sinkContainer', type: 'Expression' }
    folder: { value: '@pipeline().parameters.sinkFolder', type: 'Expression' }
  }
}]
var readSettings = {
  type: 'AzureBlobStorageReadSettings'
  recursive: true
  wildcardFileName: { value: '@pipeline().parameters.filePattern', type: 'Expression' }
}
var copyProperties = {
  sink: {
    type: 'BinarySink'
    storeSettings: {
      type: 'AzureBlobStorageWriteSettings'
      copyBehavior: 'PreserveHierarchy'
    }
  }
  enableStaging: false
}
var copyParameters = {
  lakeParameters: { type: 'Object', defaultValue: {} }
  loadMode: { type: 'String', defaultValue: 'initial' }
  sourceContainer: { type: 'String' }
  sourceFolder: { type: 'String' }
  sinkContainer: { type: 'String' }
  sinkFolder: { type: 'String' }
  filePattern: { type: 'String', defaultValue: '*' }
  watermarkStart: { type: 'String', defaultValue: '1970-01-01T00:00:00Z' }
  watermarkEnd: { type: 'String', defaultValue: '1970-01-01T00:00:00Z' }
}
var validateLake = {
  name: 'ValidateLakeDestination'
  type: 'IfCondition'
  typeProperties: {
    expression: {
      value: '@if(empty(pipeline().parameters.lakeParameters),true,and(equals(pipeline().parameters.lakeParameters.storageAccountUrl,\'${sinkBlobEndpoint}\'),and(equals(pipeline().parameters.sinkContainer,pipeline().parameters.lakeParameters.container),equals(pipeline().parameters.sinkFolder,pipeline().parameters.lakeParameters.paths.landing))))'
      type: 'Expression'
    }
    ifTrueActivities: []
    ifFalseActivities: [{
      name: 'InvalidLakeDestination'
      type: 'Fail'
      typeProperties: {
        errorCode: 'InvalidLakeDestination'
        message: 'Lake Copy must target the configured Blob account/container and raw landing prefix.'
      }
    }]
  }
}
var validateWindow = {
  name: 'ValidateLoadWindow'
  type: 'IfCondition'
  dependsOn: [{ activity: 'ValidateLakeDestination', dependencyConditions: ['Succeeded'] }]
  typeProperties: {
    expression: {
      value: '@or(equals(pipeline().parameters.loadMode,\'initial\'),and(equals(pipeline().parameters.loadMode,\'delta\'),less(ticks(pipeline().parameters.watermarkStart),ticks(pipeline().parameters.watermarkEnd))))'
      type: 'Expression'
    }
    ifTrueActivities: []
    ifFalseActivities: [{
      name: 'InvalidLoadWindow'
      type: 'Fail'
      typeProperties: {
        errorCode: 'InvalidLoadWindow'
        message: 'Use initial or delta; delta requires an increasing UTC watermark window.'
      }
    }]
  }
}
var copyActivity = {
  name: 'CopyLoad'
  type: 'IfCondition'
  dependsOn: [{ activity: 'ValidateLoadWindow', dependencyConditions: ['Succeeded'] }]
  typeProperties: {
    expression: { value: '@equals(pipeline().parameters.loadMode,\'delta\')', type: 'Expression' }
    ifFalseActivities: [{
      name: 'InitialCopy'
      type: 'Copy'
      policy: activityPolicy
      inputs: copyInputs
      outputs: copyOutputs
      typeProperties: union(copyProperties, {
        source: { type: 'BinarySource', storeSettings: readSettings }
      })
    }]
    ifTrueActivities: [{
      name: 'DeltaCopy'
      type: 'Copy'
      policy: activityPolicy
      inputs: copyInputs
      outputs: copyOutputs
      typeProperties: union(copyProperties, {
        source: {
          type: 'BinarySource'
          storeSettings: union(readSettings, {
            modifiedDatetimeStart: { value: '@pipeline().parameters.watermarkStart', type: 'Expression' }
            modifiedDatetimeEnd: { value: '@pipeline().parameters.watermarkEnd', type: 'Expression' }
          })
        }
      })
    }]
  }
}

var webProperties = {
  connectVia: ir
  authentication: { type: 'MSI', resource: environment().resourceManager }
  httpRequestTimeout: '00:02:00'
  turnOffAsync: true
  url: { value: '@variables(\'jobUrl\')', type: 'Expression' }
  datasets: []
  linkedServices: []
}

resource amlPipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = {
  parent: factory
  name: '${namePrefix}_copy_aml_v2'
  properties: {
    description: 'Initial/delta Blob copy, v2 Jobs ARM PUT, bounded polling; no registration or deployment.'
    concurrency: 1
    parameters: union(copyParameters, {
      subscriptionId: { type: 'String' }
      resourceGroup: { type: 'String' }
      workspaceName: { type: 'String' }
      jobPayload: { type: 'Object' }
    })
    variables: {
      jobUrl: { type: 'String' }
      jobStatus: { type: 'String', defaultValue: 'NotStarted' }
    }
    activities: [
      validateLake
      validateWindow
      copyActivity
      {
        name: 'SetJobUrl'
        type: 'SetVariable'
        dependsOn: [{ activity: 'CopyLoad', dependencyConditions: ['Succeeded'] }]
        typeProperties: {
          variableName: 'jobUrl'
          value: {
            value: '@concat(\'${environment().resourceManager}subscriptions/\',pipeline().parameters.subscriptionId,\'/resourceGroups/\',pipeline().parameters.resourceGroup,\'/providers/Microsoft.MachineLearningServices/workspaces/\',pipeline().parameters.workspaceName,\'/jobs/adf-\',pipeline().RunId,\'?api-version=2024-04-01\')'
            type: 'Expression'
          }
        }
      }
      {
        name: 'SubmitJob'
        type: 'WebActivity'
        policy: activityPolicy
        dependsOn: [{ activity: 'SetJobUrl', dependencyConditions: ['Succeeded'] }]
        typeProperties: union(webProperties, {
          method: 'PUT'
          headers: { 'Content-Type': 'application/json' }
          body: { value: '@string(pipeline().parameters.jobPayload)', type: 'Expression' }
        })
      }
      {
        name: 'WaitForTerminalJob'
        type: 'Until'
        dependsOn: [{ activity: 'SubmitJob', dependencyConditions: ['Succeeded'] }]
        typeProperties: {
          timeout: '0.02:00:00'
          expression: {
            value: '@contains(createArray(\'Completed\',\'Failed\',\'Canceled\',\'Cancelled\',\'NotResponding\'),variables(\'jobStatus\'))'
            type: 'Expression'
          }
          activities: [
            {
              name: 'PollDelay'
              type: 'Wait'
              typeProperties: { waitTimeInSeconds: 30 }
            }
            {
              name: 'GetJob'
              type: 'WebActivity'
              policy: activityPolicy
              dependsOn: [{ activity: 'PollDelay', dependencyConditions: ['Succeeded'] }]
              typeProperties: union(webProperties, { method: 'GET' })
            }
            {
              name: 'SetJobStatus'
              type: 'SetVariable'
              dependsOn: [{ activity: 'GetJob', dependencyConditions: ['Succeeded'] }]
              typeProperties: {
                variableName: 'jobStatus'
                value: { value: '@activity(\'GetJob\').output.properties.status', type: 'Expression' }
              }
            }
          ]
        }
      }
      {
        name: 'RequireCompletedJob'
        type: 'IfCondition'
        dependsOn: [{ activity: 'WaitForTerminalJob', dependencyConditions: ['Succeeded'] }]
        typeProperties: {
          expression: { value: '@equals(variables(\'jobStatus\'),\'Completed\')', type: 'Expression' }
          ifTrueActivities: []
          ifFalseActivities: [{
            name: 'JobDidNotSucceed'
            type: 'Fail'
            typeProperties: {
              errorCode: 'AzureMLJobFailed'
              message: { value: '@concat(\'Azure ML job ended: \',variables(\'jobStatus\'))', type: 'Expression' }
            }
          }]
        }
      }
    ]
  }
}

resource notebookPipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = if (!empty(databricksLinkedServiceName)) {
  parent: factory
  name: '${namePrefix}_copy_databricks'
  properties: {
    description: 'Copy then run the model factory Databricks training notebook with its exact widget contract.'
    concurrency: 1
    parameters: union(copyParameters, {
      notebookPath: { type: 'String' }
      notebookInputPath: { type: 'String' }
      artifactRoot: { type: 'String' }
      scenarioPath: { type: 'String' }
      experimentPath: { type: 'String' }
      modelContext: { type: 'String', defaultValue: '' }
      lakeConfig: { type: 'String', defaultValue: '' }
    })
    activities: [
      validateLake
      validateWindow
      copyActivity
      {
        name: 'RunNotebook'
        type: 'DatabricksNotebook'
        dependsOn: [{ activity: 'CopyLoad', dependencyConditions: ['Succeeded'] }]
        policy: activityPolicy
        linkedServiceName: { referenceName: databricksLinkedServiceName, type: 'LinkedServiceReference' }
        typeProperties: {
          notebookPath: { value: '@pipeline().parameters.notebookPath', type: 'Expression' }
          baseParameters: {
            input_path: { value: '@pipeline().parameters.notebookInputPath', type: 'Expression' }
            artifact_root: { value: '@pipeline().parameters.artifactRoot', type: 'Expression' }
            scenario_path: { value: '@pipeline().parameters.scenarioPath', type: 'Expression' }
            experiment_path: { value: '@pipeline().parameters.experimentPath', type: 'Expression' }
            model_context: { value: '@pipeline().parameters.modelContext', type: 'Expression' }
            lake_config: { value: '@pipeline().parameters.lakeConfig', type: 'Expression' }
          }
        }
      }
    ]
  }
}

output amlPipelineName string = amlPipeline.name
output notebookPipelineName string = empty(databricksLinkedServiceName) ? '' : '${namePrefix}_copy_databricks'
