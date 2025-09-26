// ============================================================================
// Get Application Insights Resources from AMPLS Module
// ============================================================================
// This module retrieves existing Application Insights resources connected to an AMPLS
// to avoid overwriting when adding new ones

@description('Name of the Azure Monitor Private Link Scope')
param amplsName string

@description('Resource group containing the AMPLS')
param amplsResourceGroup string

@description('Subscription containing the AMPLS')
param amplsSubscription string = subscription().subscriptionId

// Reference to existing AMPLS
resource existingAmpls 'microsoft.insights/privateLinkScopes@2021-07-01-preview' existing = {
  name: amplsName
  scope: resourceGroup(amplsSubscription, amplsResourceGroup)
}

// LIMITATION & APPROACH:
// Bicep currently cannot iterate unknown-length child collections of an existing resource
// (like scopedResources) in a compile-time safe way. The earlier attempt using list()
// caused compile diagnostics because list() cannot be resolved at the required phase
// for the for-expression enumeration.
//
// Therefore this module acts as a placeholder so that higher-level templates can keep
// a consistent contract. Discovery of existing scoped resources (App Insights, LAW,
// DCE) should be performed outside the template (CLI / PowerShell) and passed in as
// parameters to the module that updates AMPLS.
//
// If/when Bicep adds native support for enumerating child collection resources of an
// existing resource, this module can be updated to return real values.

// Outputs (empty arrays by design)
output existingApplicationInsightsIds array = []
output existingLogAnalyticsWorkspaceIds array = []
output existingDataCollectionEndpointIds array = []
output amplsExists bool = true
output amplsId string = existingAmpls.id
