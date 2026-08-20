@description('Name of the existing Azure Automation account that will host the Python runbook.')
param automationAccountName string

@description('Azure region of the existing Automation account, for example westeurope.')
param automationAccountLocation string

@description('Name assigned to the runbook.')
param runbookName string = 'FoundryUsageReport'

@description('HTTPS URI of the published foundry_usage_report.py file. The Automation account must be able to read it.')
param runbookContentUri string

@description('Tags applied to the runbook.')
param tags object = {}

resource automationAccount 'Microsoft.Automation/automationAccounts@2023-11-01' existing = {
  name: automationAccountName
}

resource runbook 'Microsoft.Automation/automationAccounts/runbooks@2023-11-01' = {
  parent: automationAccount
  name: runbookName
  location: automationAccountLocation
  tags: tags
  properties: {
    runbookType: 'Python3'
    logProgress: true
    logVerbose: true
    publishContentLink: {
      uri: runbookContentUri
    }
  }
}

output runbookResourceId string = runbook.id
