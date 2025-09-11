// Test file to debug naming values
param randomValue string = '2e9f171f16'
param addAIFoundryV21 bool = true

// Replicate the naming logic
var randomSalt = substring(uniqueString(subscription().subscriptionId, 'test-rg'), 0, 5)
var cleanRandomValue = !empty(randomValue) ? toLower(replace(replace(randomValue, '-', ''), '_', '')) : randomSalt
var aifRandom = take('aif${cleanRandomValue}',12)

output cleanRandomValue string = cleanRandomValue
output aifRandom string = aifRandom
output aifRandomLength int = length(aifRandom)

// Test the actual value with your input
output testValue string = take('aif2e9f171f16', 12)
output testLength int = length(take('aif2e9f171f16', 12))
