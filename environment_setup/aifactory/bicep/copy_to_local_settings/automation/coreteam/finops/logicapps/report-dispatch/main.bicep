targetScope = 'resourceGroup'

@description('A NEW, dedicated report-only Consumption Logic App. Do not use the network-throttling workflow name.')
param workflowName string = 'aifactory-report-dispatch'
param location string = resourceGroup().location
param automationAccountName string
param automationAccountResourceGroup string
@description('Entra object ID of the caller permitted to dispatch reports (not an application/client ID).')
param allowedCallerObjectId string

var automationAccountResourceId = resourceId(automationAccountResourceGroup, 'Microsoft.Automation/automationAccounts', automationAccountName)

resource workflow 'Microsoft.Logic/workflows@2019-05-01' = {
  name: workflowName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: {
    'aifactory-purpose': 'report-dispatch'
    'aifactory-report-protocol': '1'
  }
  properties: {
    state: 'Enabled'
    accessControl: {
      triggers: {
        // Supported by Logic Apps; not yet represented by the Bicep resource type schema.
        #disable-next-line BCP037
        sasAuthenticationPolicy: {
          state: 'Disabled'
        }
        openAuthenticationPolicies: {
          policies: {
            reportCaller: {
              type: 'AAD'
              claims: [
                { name: 'iss', value: 'https://sts.windows.net/${tenant().tenantId}/' }
                { name: 'aud', value: environment().authentication.audiences[0] }
                { name: 'oid', value: allowedCallerObjectId }
              ]
            }
          }
        }
      }
    }
    parameters: {
      automationAccountResourceId: { value: automationAccountResourceId }
      subscriptionId: { value: subscription().subscriptionId }
      tenantId: { value: tenant().tenantId }
      armEndpoint: { value: environment().resourceManager }
    }
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: {
        automationAccountResourceId: { type: 'String' }
        subscriptionId: { type: 'String' }
        tenantId: { type: 'String' }
        armEndpoint: { type: 'String' }
      }
      triggers: {
        manual: {
          type: 'Request'
          kind: 'Http'
          runtimeConfiguration: {
            secureData: { properties: [ 'inputs', 'outputs' ] }
          }
          inputs: {
            method: 'POST'
            schema: {
              type: 'object'
              additionalProperties: false
              required: [ 'version', 'report_type', 'job_id', 'parameters' ]
              properties: {
                version: { type: 'integer', enum: [ 1 ] }
                report_type: { type: 'string', enum: [ 'foundry-tokens', 'showback' ] }
                job_id: { type: 'string', pattern: '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' }
                parameters: {
                  type: 'object'
                  additionalProperties: false
                  required: [ 'ConfigJson', 'ReportFormat', 'NoUpload', 'SubscriptionId', 'TenantId', 'ProjectNumber', 'ProjectResourceGroup', 'CommonResourceGroup', 'Env', 'LookbackDays' ]
                  properties: {
                    ConfigJson: { type: 'string', maxLength: 200000 }
                    ReportFormat: { type: 'string', enum: [ 'Json' ] }
                    NoUpload: { type: 'string', enum: [ 'true' ] }
                    SubscriptionId: { type: 'string' }
                    TenantId: { type: 'string' }
                    ProjectNumber: { type: 'string', pattern: '^[0-9]{1,10}$' }
                    ProjectResourceGroup: { type: 'string', minLength: 1 }
                    CommonResourceGroup: { type: 'string', minLength: 1 }
                    Env: { type: 'string', minLength: 1 }
                    LookbackDays: { type: 'string', pattern: '^([1-9]|[1-8][0-9]|90)$' }
                  }
                }
              }
            }
          }
        }
      }
      actions: {
        Validate_target: {
          type: 'If'
          expression: {
            and: [
              { equals: [ '@toLower(triggerBody()[\'parameters\'][\'SubscriptionId\'])', '@toLower(parameters(\'subscriptionId\'))' ] }
              { equals: [ '@toLower(triggerBody()[\'parameters\'][\'TenantId\'])', '@toLower(parameters(\'tenantId\'))' ] }
            ]
          }
          actions: {
            Create_report_job: {
              type: 'Http'
              runtimeConfiguration: {
                secureData: { properties: [ 'inputs', 'outputs' ] }
              }
              inputs: {
                method: 'PUT'
                uri: '@concat(parameters(\'armEndpoint\'), substring(parameters(\'automationAccountResourceId\'), 1), \'/jobs/\', triggerBody()[\'job_id\'], \'?api-version=2023-11-01\')'
                authentication: { type: 'ManagedServiceIdentity', audience: '@parameters(\'armEndpoint\')' }
                retryPolicy: { type: 'none' }
                body: {
                  properties: {
                    runbook: {
                      name: '@if(equals(triggerBody()[\'report_type\'], \'showback\'), \'Update-ShowbackReport\', \'Update-FoundryTokenReport\')'
                    }
                    parameters: {
                      ConfigJson: '@triggerBody()[\'parameters\'][\'ConfigJson\']'
                      ReportFormat: 'Json'
                      NoUpload: 'true'
                      SubscriptionId: '@parameters(\'subscriptionId\')'
                      TenantId: '@parameters(\'tenantId\')'
                      ProjectNumber: '@triggerBody()[\'parameters\'][\'ProjectNumber\']'
                      ProjectResourceGroup: '@triggerBody()[\'parameters\'][\'ProjectResourceGroup\']'
                      CommonResourceGroup: '@triggerBody()[\'parameters\'][\'CommonResourceGroup\']'
                      Env: '@triggerBody()[\'parameters\'][\'Env\']'
                      LookbackDays: '@triggerBody()[\'parameters\'][\'LookbackDays\']'
                    }
                  }
                }
              }
            }
            Accepted: {
              type: 'Response'
              kind: 'Http'
              runAfter: { Create_report_job: [ 'Succeeded' ] }
              inputs: {
                statusCode: 202
                body: {
                  run_id: '@triggerBody()[\'job_id\']'
                  automation_account_resource_id: '@parameters(\'automationAccountResourceId\')'
                }
              }
            }
            Failed: {
              type: 'Response'
              kind: 'Http'
              runAfter: { Create_report_job: [ 'Failed', 'TimedOut' ] }
              inputs: {
                statusCode: 502
                body: { error: 'Report job could not be dispatched.' }
              }
            }
          }
          else: {
            actions: {
              Invalid_target: {
                type: 'Response'
                kind: 'Http'
                inputs: {
                  statusCode: 400
                  body: { error: 'Report target does not match the configured subscription and tenant.' }
                }
              }
            }
          }
        }
      }
      outputs: {}
    }
  }
}

@description('Grant this identity only Automation job creation/read and the two report runbook read permissions on the existing Automation Account. No role assignments or schedules are changed by this template.')
output dispatcherPrincipalId string = workflow.identity.principalId
output workflowResourceId string = workflow.id
output reportAutomationAccountResourceId string = automationAccountResourceId
