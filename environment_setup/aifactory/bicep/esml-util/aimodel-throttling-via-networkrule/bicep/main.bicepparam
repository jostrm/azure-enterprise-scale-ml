using './main.bicep'

// ---------------------------------------------------------------------------
// Example parameters. Copy & adjust to your AI Factory environment.
// Deploy with:
//   az deployment sub create \
//     --location swedencentral \
//     --template-file bicep/main.bicep \
//     --parameters bicep/main.bicepparam
// ---------------------------------------------------------------------------

// --- Scope: one project RG (change to 'Subscription' to cap the whole sub) ---
param throttleScope = 'ResourceGroup'

// OPTION A - AI Factory exists: derive the project RG from the naming convention.
//   Set esmlAifactoryExists=true and fill the naming params; leave targetResourceGroup empty.
param esmlAifactoryExists = false
param env = 'dev'
param aifactoryPrefixRG = ''     // e.g. 'acme-1-'
param projectPrefix = ''
param projectSuffix = ''
param projectNumber = ''         // e.g. '001'
param locationSuffix = ''        // e.g. 'swc'
param aifactorySuffixRG = ''     // e.g. '-001'

// OPTION B - No AI Factory: pass the project RG explicitly.
param targetResourceGroup = 'acme-1-esml-project001-swc-dev-001-rg'

// Management RG hosting the Logic App + Action Group (defaults to targetResourceGroup if empty)
param throttleResourceGroup = ''

param location = 'swedencentral'
param namePrefix = 'esml-throttle-prj001'

// Choose which Logic App to create/use as the throttle executor (pre-req: hosting RG must exist).
// Leave empty to default to "<namePrefix>-logic".
param logicAppName = 'esml-throttle-prj001-logic'

// Pre-req (recommended): Log Analytics workspace behind your Application Insights, for Logic App telemetry.
param logAnalyticsWorkspaceResourceId = ''

param tags = {
  createdBy: 'esml-aimodel-throttling'
  purpose: 'genai-consumption-cap'
}

// --- Cost budget trigger ---
param enableBudget = true
param budgetAmount = 100                 // $100/month cap (billing currency)
param actualThresholdPercent = 100       // throttle when ACTUAL spend hits $100
param forecastThresholdPercent = 90      // early throttle when FORECAST hits $90
param budgetStartDate = '2026-07-01'     // must be the first of a month

// --- Token scheduled-query trigger (optional; needs a workspace with Foundry metrics) ---
param enableTokenAlert = false
param workspaceResourceId = ''
param workspaceResourceGroup = ''
param tokenThreshold = 50000000

// --- Extra notifications ---
param notifyEmails = []
