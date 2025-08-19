# Version 1.22

# 01-foundation.bicep
- aifactoryVersionMajor
- aifactoryVersionMinor
- useAdGroups
- env
- location
- locationSuffix
- projectNumber
- miACAExists
- miPrjExists
- keyvaultExists
- storageAccount1001Exists
- zoneAzurecontainerappsExists
- zonePostgresExists
- zoneSqlExists
- zoneMongoExists
- zoneRedisExists
- vnetNameBase
- vnetResourceGroup_param
- vnetNameFull_param
- network_env
- genaiSubnetId
- aksSubnetId
- acaSubnetId
- centralDnsZoneByPolicyInHub
- privateDnsAndVnetLinkAllGlobalLocation
- privDnsSubscription_param
- privDnsResourceGroup_param
- commonRGNamePrefix
- aifactorySuffixRG
- commonResourceSuffix
- resourceSuffix
- commonResourceGroup_param
- technicalContactId
- technicalContactEmail
- technicalAdminsObjectID
- technicalAdminsEmail
- projectServicePrincipleOID_SeedingKeyvaultName
- inputKeyvault
- inputKeyvaultResourcegroup
- inputKeyvaultSubscription
- tags
- tagsProject
- enableDebugging
- randomValue
- aifactorySalt10char

# 02-cognitive-services.bicep

# UTILS

## Check unused PARAMETERS in BICEP file

```powershell
$content = Get-Content "01-foundation.bicep" -Raw
$params = @()
$content -split "`n" | ForEach-Object {
    if ($_ -match "^param\s+(\w+)") {
        $params += $matches[1]
    }
}

$unused = @()
foreach ($param in $params) {
    $pattern = "\b$param\b"
    $matches = [regex]::Matches($content, $pattern)
    $nonParamMatches = $matches | Where-Object { 
        $line = ($content.Substring(0, $_.Index) -split "`n").Count
        $lineText = ($content -split "`n")[$line - 1]
        $lineText -notmatch "^param\s+$param"
    }
    if ($nonParamMatches.Count -eq 0) {
        $unused += $param
        Write-Host "UNUSED: $param"
    }
}

```

## List parameters in BICEP file
```powershell
Get-Content 01-foundation.bicep | Select-String "^param\s+\w+" | ForEach-Object { ($_ -split "\s+")[1] }
```

## List parameters in BICEP file (v2)
```powershell
echo "=== 06-ml-platform.bicep parameters ===" && Get-Content 06-ml-platform.bicep | Select-String "^param\s+\w+" | ForEach-Object { ($_ -split "\s+")[1] }
```

## GIT - restore single file
```
git checkout HEAD -- 02-cognitive-services.bicep
```