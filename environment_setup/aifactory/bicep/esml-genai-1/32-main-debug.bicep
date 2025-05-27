targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

param name string
param location string

output locationSuffix string = '${location}-${name}'
