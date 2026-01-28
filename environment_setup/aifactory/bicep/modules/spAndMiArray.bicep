@secure()
param servicePrincipleOIDFromSecret string
param managedIdentityOID string
@description('Include the managed identity in the output array when true; skip it when false or empty.')
param includeManagedIdentity bool = true

// Build arrays only when non-empty; prevents empty-string elements from being emitted.
var serviceArray = empty(servicePrincipleOIDFromSecret) ? [] : [servicePrincipleOIDFromSecret]
var managedIdentityArray = includeManagedIdentity && !empty(managedIdentityOID) ? [managedIdentityOID] : []

// Order preserved: service principal first, managed identity second (when included)
#disable-next-line outputs-should-not-contain-secrets
output spAndMiArray array = concat(serviceArray, managedIdentityArray)
