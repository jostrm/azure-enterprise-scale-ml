// =============================================================================
// budget.resourcegroup.bicep
// Resource-group-scoped cost budget (one AI Factory project RG). When actual OR
// forecasted spend crosses the threshold, it notifies the Action Group.
// =============================================================================
targetScope = 'resourceGroup'

@description('Budget name.')
param budgetName string

@description('Monthly budget amount (in the billing currency).')
param amount int

@description('Percent of amount at which the ACTUAL-spend notification fires (e.g. 100).')
param actualThresholdPercent int = 100

@description('Percent of amount at which the FORECASTED-spend notification fires (e.g. 90).')
param forecastThresholdPercent int = 90

@description('Action Group resource id to notify.')
param actionGroupId string

@description('Budget start date (first of a month), format yyyy-MM-dd.')
param startDate string

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [ resourceGroup().name ]
      }
    }
    notifications: {
      Actual_GreaterThan_Threshold: {
        enabled: true
        operator: 'GreaterThan'
        threshold: actualThresholdPercent
        thresholdType: 'Actual'
        contactEmails: []
        contactGroups: [ actionGroupId ]
      }
      Forecast_GreaterThan_Threshold: {
        enabled: true
        operator: 'GreaterThan'
        threshold: forecastThresholdPercent
        thresholdType: 'Forecasted'
        contactEmails: []
        contactGroups: [ actionGroupId ]
      }
    }
  }
}

output budgetId string = budget.id
