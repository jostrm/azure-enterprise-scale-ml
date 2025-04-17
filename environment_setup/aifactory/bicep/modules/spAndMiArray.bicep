@secure()
param servicePrincipleOIDFromSecret string
param managedIdentityOID string

var toArray = [servicePrincipleOIDFromSecret, managedIdentityOID]

#disable-next-line outputs-should-not-contain-secrets
output spAndMiArray array = toArray
