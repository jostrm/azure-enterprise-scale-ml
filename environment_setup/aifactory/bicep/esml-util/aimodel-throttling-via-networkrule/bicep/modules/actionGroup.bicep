// =============================================================================
// actionGroup.bicep
// Action Group that invokes the throttle Logic App when a budget or token
// metric alert fires.
// =============================================================================

@description('Name of the Action Group.')
param actionGroupName string

@description('Short name (<=12 chars) shown in notifications.')
@maxLength(12)
param shortName string = 'esmlthrot'

@description('Name of the throttle Logic App (in this resource group) to invoke.')
param logicAppName string

@description('Name of the Logic App trigger to call.')
param triggerName string = 'manual'

@description('Optional email addresses to also notify.')
param emailReceivers array = []

@description('Tags.')
param tags object = {}

// Reference the existing Logic App so we can read its callback URL without
// exposing it as a template output (secret-safe).
resource logicApp 'Microsoft.Logic/workflows@2019-05-01' existing = {
  name: logicAppName
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: actionGroupName
  location: 'Global'
  tags: tags
  properties: {
    groupShortName: shortName
    enabled: true
    logicAppReceivers: [
      {
        name: 'throttleLogicApp'
        resourceId: logicApp.id
        callbackUrl: listCallbackUrl('${logicApp.id}/triggers/${triggerName}', '2019-05-01').value
        useCommonAlertSchema: true
      }
    ]
    emailReceivers: [for (email, i) in emailReceivers: {
      name: 'email${i}'
      emailAddress: email
      useCommonAlertSchema: true
    }]
  }
}

output actionGroupId string = actionGroup.id
