targetScope = 'resourceGroup'

// ============================================================================
// WHY AI SEARCH NEEDS SHARED PRIVATE LINKS TO AI FOUNDRY
// (even when both have private endpoints in the same VNet)
// ============================================================================
//
// INBOUND vs OUTBOUND - the key distinction:
//
//   A Private Endpoint is an INBOUND construct.
//   It places a network interface with a private IP in your VNet so that
//   traffic can flow FROM your VNet INTO a managed service privately.
//
//     VNet client  --(private IP)-->  [Private Endpoint NIC]  -->  AI Search
//     VNet client  --(private IP)-->  [Private Endpoint NIC]  -->  AI Foundry
//
//   Both AI Search and AI Foundry having private endpoints on the same VNet/subnet
//   means YOUR code and VMs can reach both services without leaving the VNet. ✓
//
// The problem - AI Search makes OUTBOUND calls:
//
//   Azure AI Search is a fully managed PaaS service. Its compute (indexers,
//   skillsets, vectorizers, semantic rankers) runs inside Microsoft's managed
//   infrastructure, NOT inside your VNet. Only its NIC (the private endpoint)
//   is in your VNet.
//
//   When AI Search executes a skillset or vectorizer it must call out TO
//   Azure OpenAI / Cognitive Services / AI Foundry. These outbound calls
//   originate from Microsoft's managed AI Search backend, not from your VNet:
//
//     [AI Search backend in MSFT infra]  --OUTBOUND-->  AI Foundry ???
//
//   If AI Foundry has public network access disabled (privateEndpointOnly),
//   these outbound calls from AI Search are BLOCKED - because they arrive
//   over the public internet, not through a private endpoint.
//
//   Having a private endpoint on AI Search (inbound) does NOT grant AI Search's
//   own backend the ability to make outbound private calls to other resources.
//
// The solution - Shared Private Link (Outbound from the managed service):
//
//   A Shared Private Link is a private endpoint that the managed AI Search
//   service itself provisions FROM its backend infrastructure INTO your resource.
//   It creates a dedicated, private, outbound channel:
//
//     [AI Search backend]  --(Shared Private Link / private endpoint)-->  AI Foundry
//
//   This is entirely separate from the inbound private endpoint on AI Search.
//   Once approved, AI Search's backend can reach AI Foundry over RFC-1918
//   addresses, satisfying Foundry's "deny public traffic" network policy.
//
// Summary table:
//   Private endpoint on AI Search   → Your VNet can reach AI Search    (INBOUND  to AI Search)
//   Private endpoint on AI Foundry  → Your VNet can reach AI Foundry   (INBOUND  to AI Foundry)
//   Shared Private Link (this file) → AI Search can reach AI Foundry   (OUTBOUND from AI Search)
//
// The three groupIds created here:
//   openai_account          – AI Search calls the OpenAI endpoint for vectorization / completions
//   cognitiveservices_account – AI Search calls built-in Cognitive skills (OCR, NER, key phrases)
//   foundry_account         – AI Search calls the Foundry Agent Service for grounding & retrieval
// ============================================================================

@description('Name of the existing Azure AI Search service that will request the shared private link')
param aiSearchName string

@description('Resource ID of the Azure AI Foundry account that will receive the shared private link request')
param aiFoundryResourceId string

@description('Azure region for the shared private link request')
param location string

@description('Optional message included with the shared private link request')
param requestMessage string = 'Azure AI Search shared private link to Azure AI Foundry'

resource aiSearchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: aiSearchName
}

// Link 1: openai_account - enables AI Search to call the Azure OpenAI endpoint on the Foundry account
// over a private channel (used for vectorization, reranking, and chat completions in RAG pipelines).
resource sharedPrivateLink 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2025-05-01' = if (!empty(aiFoundryResourceId) && !empty(aiSearchName)) {
  name: 'shared-pe-foundry-openai'
  parent: aiSearchService
  properties: {
    privateLinkResourceId: aiFoundryResourceId
    groupId: 'openai_account'
    requestMessage: requestMessage
    resourceRegion: location
  }
}

// Link 2: cognitiveservices_account - enables AI Search to reach the Cognitive Services endpoint on
// the same Foundry account (used for built-in skills such as OCR, entity recognition, and key phrases).
resource sharedPrivateLink2 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2025-05-01' = if (!empty(aiFoundryResourceId) && !empty(aiSearchName)) {
  name: 'shared-pe-foundry-cogsvc'
  parent: aiSearchService
  properties: {
    privateLinkResourceId: aiFoundryResourceId
    groupId: 'cognitiveservices_account'
    requestMessage: requestMessage
    resourceRegion: location
  }
  dependsOn: [
    sharedPrivateLink
  ]
}

// Link 3: foundry_account - enables AI Search to reach the AI Foundry control-plane endpoint
// (used by the Foundry Agent Service when it calls AI Search for grounding and vector retrieval).
resource sharedPrivateLink3 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2025-05-01' = if (!empty(aiFoundryResourceId) && !empty(aiSearchName)) {
  name: 'shared-pe-foundry-account'
  parent: aiSearchService
  properties: {
    privateLinkResourceId: aiFoundryResourceId
    groupId: 'foundry_account'
    requestMessage: requestMessage
    resourceRegion: location
  }
  dependsOn: [
    sharedPrivateLink2
  ]
}


output sharedPrivateLinkName string = !empty(aiFoundryResourceId) && !empty(aiSearchName) ? sharedPrivateLink.name : ''
output sharedPrivateLinkName2 string = !empty(aiFoundryResourceId) && !empty(aiSearchName) ? sharedPrivateLink2.name : ''
output sharedPrivateLinkName3 string = !empty(aiFoundryResourceId) && !empty(aiSearchName) ? sharedPrivateLink3.name : ''
