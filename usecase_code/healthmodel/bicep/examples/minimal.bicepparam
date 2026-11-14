// Hand-authored, Python-free example: one layer with a Foundry account and AI Search.
// Signals come straight from the shared catalog, so thresholds stay identical to the
// generated models. Replace the subscription, resource group and resource names.
//   az deployment group create -g <project-rg> -f ../main.bicep -p minimal.bicepparam
using '../main.bicep'

var catalog = loadJsonContent('../../catalog/signal-catalog.json')
var foundry = filter(catalog.profiles, p => p.key == 'foundry')[0]
var search = filter(catalog.profiles, p => p.key == 'search')[0]
var projectRg = 'contoso-esml-project001-sdc-dev-001-rg'
var resourcePrefix = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/${projectRg}/providers'

param healthModelName = 'hm-contoso-prj001-sdc-dev-001'
param location = 'swedencentral'
param rootDisplayName = 'AI Factory project 001 (dev)'
param readerResourceGroups = [
  projectRg
]
param alertPolicy = {
  rootUnhealthySeverity: 'Sev1'
  layerUnhealthySeverity: 'Sev2'
}
param entities = [
  {
    name: 'layer-genai'
    role: 'layer'
    properties: {
      displayName: 'Generative AI and agents'
      impact: 'Standard'
      signalGroups: {
        dependencies: {
          aggregationType: 'WorstOf'
          ignoreUnknown: true
        }
      }
    }
  }
  {
    name: 'foundry-account'
    role: 'resource'
    properties: {
      displayName: 'AI Foundry account: aif2contoso001dev'
      impact: 'Standard'
      signalAggregationGroups: foundry.signalAggregationGroups
      signalGroups: {
        azureResource: {
          authenticationSetting: 'systemassigned'
          azureResourceId: '${resourcePrefix}/Microsoft.CognitiveServices/accounts/aif2contoso001dev'
          resourceHealth: {
            enabled: 'Enabled'
          }
          signals: foundry.signals
        }
      }
    }
  }
  {
    name: 'search-service'
    role: 'resource'
    properties: {
      displayName: 'AI Search: srch-contoso-001-dev'
      impact: 'Standard'
      signalGroups: {
        azureResource: {
          authenticationSetting: 'systemassigned'
          azureResourceId: '${resourcePrefix}/Microsoft.Search/searchServices/srch-contoso-001-dev'
          resourceHealth: {
            enabled: 'Enabled'
          }
          signals: search.signals
        }
      }
    }
  }
]
param relationships = [
  {
    name: 'root-to-layer-genai'
    parentEntityName: 'hm-contoso-prj001-sdc-dev-001'
    childEntityName: 'layer-genai'
  }
  {
    name: 'layer-genai-to-foundry-account'
    parentEntityName: 'layer-genai'
    childEntityName: 'foundry-account'
  }
  {
    name: 'layer-genai-to-search-service'
    parentEntityName: 'layer-genai'
    childEntityName: 'search-service'
  }
]
