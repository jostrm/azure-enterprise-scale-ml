// Optional action group for health-state alerts (e-mail receivers, common alert schema).
targetScope = 'resourceGroup'

@description('Action group name.')
param name string

@description('Short name shown in notifications (max 12 characters).')
@maxLength(12)
param shortName string

@description('E-mail addresses that receive health-state alerts.')
param emails array = []

@description('Resource tags.')
param tags object = {}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: name
  location: 'global'
  tags: tags
  properties: {
    groupShortName: shortName
    enabled: true
    emailReceivers: [for (email, index) in emails: {
      name: 'email-${index}'
      emailAddress: email
      useCommonAlertSchema: true
    }]
  }
}

output id string = actionGroup.id
