targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

param name string
param location string
param webAppServicePlanExists bool = false
param keyvaultExists bool = false

output locationSuffix string = '${location}-${name}'
output keyvaultExistsOut bool = keyvaultExists
output webAppServicePlanExistsOut bool = webAppServicePlanExists
