// AI Factory Azure Monitor health model (preview).
// Deploy to the project resource group (modelScope=project) or the common resource
// group (modelScope=common). Entities and relationships are rendered from
// catalog/signal-catalog.json by the planner (aif_healthmodel.py plan|deploy) or written by hand.
targetScope = 'resourceGroup'

metadata name = 'AI Factory health model'
metadata description = 'State-based health for an Enterprise Scale AI Factory project or its common services, with default health-state alerts.'

@description('Health model name: lowercase, 3-44 characters. The implicit root entity has the same name.')
@minLength(3)
@maxLength(44)
param healthModelName string

@description('Region for the health model resource. Must be a Microsoft.CloudHealth region (for example swedencentral, westeurope, centralus).')
param location string

@description('project = one AI Factory project RG (+ shared common dependencies); common = the factory common RG (+ nested project models).')
@allowed([
  'project'
  'common'
])
param modelScope string = 'project'

@description('Display name of the root entity, for example "AI Factory project 001 (dev)".')
param rootDisplayName string

@description('Health objective of the root entity: target percentage of time the workload is healthy.')
@minValue(0)
@maxValue(100)
param healthObjective int = 99

@description('Entities rendered by the planner: [{ name, role: layer|resource, properties }].')
param entities array = []

@description('Relationships rendered by the planner: [{ name, parentEntityName, childEntityName }]. The root entity name equals healthModelName.')
param relationships array = []

@description('Resource groups in this subscription where the model identity gets Monitoring Reader (metrics, Resource Health, nested models).')
param readerResourceGroups array = []

@description('Create the Monitoring Reader role assignments. Set false when roles are granted outside this deployment.')
param assignReaderRoles bool = true

@description('Health-state alert policy. An empty severity disables that alert. Severities: Sev0 (critical) to Sev4 (verbose).')
param alertPolicy object = {
  rootUnhealthySeverity: 'Sev1'
  rootDegradedSeverity: 'Sev3'
  layerUnhealthySeverity: 'Sev2'
  layerDegradedSeverity: ''
  resourceUnhealthySeverity: ''
  resourceDegradedSeverity: ''
}

@description('Existing action group resource IDs notified by health-state alerts (at most five per entity, including a created group).')
@maxLength(5)
param actionGroupIds array = []

@description('Create an action group with e-mail receivers for health-state alerts.')
param createActionGroup bool = false

@description('E-mail receivers of the created action group.')
param actionGroupEmails array = []

@description('Short name of the created action group (max 12 characters, shown in notifications).')
@maxLength(12)
param actionGroupShortName string = 'aif-health'

@description('Tags for the health model and the created action group.')
param tags object = {}

var managedBy = 'aifactory-healthmodel'
var authSettingName = 'systemassigned'
var monitoringReaderRoleId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var policy = union({
  rootUnhealthySeverity: 'Sev1'
  rootDegradedSeverity: 'Sev3'
  layerUnhealthySeverity: 'Sev2'
  layerDegradedSeverity: ''
  resourceUnhealthySeverity: ''
  resourceDegradedSeverity: ''
}, alertPolicy)
var modelTags = union(tags, {
  managedBy: managedBy
  'aifactory-healthmodel': modelScope
})

@description('Health-state alert configuration for one entity.')
func entityAlerts(unhealthySeverity string, degradedSeverity string, groups array, label string) object =>
  union(
    empty(unhealthySeverity)
      ? {}
      : {
          unhealthy: union(
            {
              severity: unhealthySeverity
              description: take('${label} is unhealthy. Open the AI Factory health model to see the failing signals and dependencies.', 1000)
            },
            empty(groups) ? {} : { actionGroupIds: groups }
          )
        },
    empty(degradedSeverity)
      ? {}
      : {
          degraded: union(
            {
              severity: degradedSeverity
              description: take('${label} is degraded. Open the AI Factory health model to see the failing signals and dependencies.', 1000)
            },
            empty(groups) ? {} : { actionGroupIds: groups }
          )
        }
  )

module actionGroup 'modules/action-group.bicep' = if (createActionGroup) {
  name: take('hm-ag-${uniqueString(resourceGroup().id, healthModelName)}', 64)
  params: {
    name: 'ag-${healthModelName}'
    shortName: actionGroupShortName
    emails: actionGroupEmails
    tags: modelTags
  }
}

var alertActionGroupIds = createActionGroup ? concat(actionGroupIds, [actionGroup!.outputs.id]) : actionGroupIds

#disable-next-line BCP081
resource healthModel 'Microsoft.CloudHealth/healthmodels@2026-09-01-preview' = {
  name: healthModelName
  location: location
  tags: modelTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

module readerRoles 'modules/reader-role.bicep' = [for group in readerResourceGroups: if (assignReaderRoles) {
  name: take('hm-reader-${uniqueString(group, healthModelName)}', 64)
  scope: resourceGroup(group)
  params: {
    principalId: healthModel.identity.principalId
    roleDefinitionId: monitoringReaderRoleId
    healthModelName: healthModelName
  }
}]

#disable-next-line BCP081
resource authSetting 'Microsoft.CloudHealth/healthmodels/authenticationsettings@2026-09-01-preview' = {
  parent: healthModel
  name: authSettingName
  properties: {
    authenticationKind: 'ManagedIdentity'
    displayName: 'Health model system-assigned identity'
    managedIdentityName: 'SystemAssigned'
  }
}

#disable-next-line BCP081
resource rootEntity 'Microsoft.CloudHealth/healthmodels/entities@2026-09-01-preview' = {
  parent: healthModel
  name: healthModelName
  properties: {
    displayName: rootDisplayName
    healthObjective: healthObjective
    impact: 'Standard'
    tags: {
      managedBy: managedBy
      role: 'root'
      modelScope: modelScope
    }
    alerts: entityAlerts(policy.rootUnhealthySeverity, policy.rootDegradedSeverity, alertActionGroupIds, rootDisplayName)
    signalGroups: {
      dependencies: {
        aggregationType: 'WorstOf'
        ignoreUnknown: true
      }
    }
  }
  dependsOn: [
    authSetting
  ]
}

@batchSize(10)
#disable-next-line BCP081
resource modelEntities 'Microsoft.CloudHealth/healthmodels/entities@2026-09-01-preview' = [for entity in entities: {
  parent: healthModel
  name: entity.name
  properties: union(entity.properties, {
    alerts: entity.role == 'layer'
      ? entityAlerts(policy.layerUnhealthySeverity, policy.layerDegradedSeverity, alertActionGroupIds, entity.properties.displayName)
      : entityAlerts(policy.resourceUnhealthySeverity, policy.resourceDegradedSeverity, alertActionGroupIds, entity.properties.displayName)
  })
  dependsOn: [
    authSetting
    rootEntity
  ]
}]

@batchSize(10)
#disable-next-line BCP081
resource modelRelationships 'Microsoft.CloudHealth/healthmodels/relationships@2026-09-01-preview' = [for relationship in relationships: {
  parent: healthModel
  name: relationship.name
  properties: {
    parentEntityName: relationship.parentEntityName
    childEntityName: relationship.childEntityName
    tags: {
      managedBy: managedBy
    }
  }
  dependsOn: [
    rootEntity
    modelEntities
  ]
}]

output healthModelId string = healthModel.id
output healthModelName string = healthModel.name
output principalId string = healthModel.identity.principalId
output entityCount int = length(entities) + 1
output relationshipCount int = length(relationships)
output alertActionGroupIds array = alertActionGroupIds
