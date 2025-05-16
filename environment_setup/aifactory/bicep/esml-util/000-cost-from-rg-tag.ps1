# Licensed under the MIT license.
# Copyright (C) 2022 Helsedirektoratet

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, 
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

<#
.SYNOPSIS
The script returns monthly data from the Usage Details API https://docs.microsoft.com/en-us/rest/api/consumption/usage-details/list
and generates excel sheets using the ImportExcel module. The API call is designed to retrieve consumption for a month.
In turn, both raw data and monthly grouped data is grouped by the 'project' tag, resource group, and resource name. The raw script output assumes the tags
'cost-center', 'project' and 'environment' are in place. Edit the script to suit your own environment
This script was inspired by Kristofer Liljeblad's script https://gist.github.com/krist00fer/9e8ff18ac4f22863d41aec0753ebdac4
.EXAMPLE

$env:ClientSecret = 'my_clientsecretin_in_rawtext"

Get consumption data for the previous billing period (default)
Get-AzureUsageCost.ps1 -ClientSecret $env:ClientSecret

Get consumption data for a specified billing period
Get-AzureUsageCost.ps1 -ClientSecret $env:ClientSecret -YearMonth = 201903
#>

param(
    [string]$YearMonth = (Get-Date).AddMonths(-1).ToString("yyyyMM"),
    [Parameter(Mandatory)]
    [string]$ClientSecret,
    [switch]$RunInPipeline
)

# Replace the following configuration settings
$tenantId = "yourtenanthere.onmicrosoft.com"
$clientId = "xxxxxxxxxxxxxxxxx"
$subscriptionIds = @(
    "xxx-yyy"
    "yyy-xxx"
)

if ($RunInPipeline) {
    Write-Host "Installing required modules as you are running in context of a pipeline..." -ForegroundColor Yellow
    Install-Module ImportExcel -Force
    Import-Module ImportExcel -Force
}

# Login

$loginUri = "https://login.microsoftonline.com/$tenantId/oauth2/token?api-version=1.0"

$body = @{
    grant_type    = "client_credentials"
    resource      = "https://management.core.windows.net/"
    client_id     = $clientId
    client_secret = $ClientSecret
}

Write-Host "Authenticating" 

$loginResponse = Invoke-RestMethod $loginUri -Method Post -Body $body
$authorization = $loginResponse.token_type + ' ' + $loginResponse.access_token
# Use the same header in all the calls, so save authorization in a header dictionary

$headers = @{
    authorization = $authorization
}
$ErrorActionPreference = "Continue"

# Usage Details API

$Date = (Get-Date -AsUTC).ToString("yyyy-MM-dd-HH.mm.ssZ")
$billingPeriod = $YearMonth + "01"
$excelFile = "./output/costoverview-$billingPeriod.xlsx"
$billingString = "/providers/Microsoft.Billing/billingPeriods/$billingPeriod/providers"
$usageRows = New-Object System.Collections.ArrayList

foreach ($subId in $subscriptionIds) {
    $usageUri = "https://management.azure.com/subscriptions/$subId$billingString/Microsoft.Consumption/usageDetails?`$expand=meterDetails&api-version=2021-10-01"

    Write-Host "Querying Azure Usage API for subscription $subId"

    do {
        Write-Host "."
        $usageResult = Invoke-RestMethod $usageUri -Headers $headers -ContentType "application/json"

        foreach ($usageRow in $usageResult.value) {
            $usageRows.Add($usageRow) > $null
        }

        $usageUri = $usageResult.nextLink

        # If there's a continuation, then call API again
    } while ($usageUri)
}

# Fine tune result
$usageRows = $usageRows | Sort-Object -Property { $_.properties.date }, { $_.properties.tags.project }, { $_.properties.resourceName }

$reportResult = $usageRows | Select-Object @{ N = 'DateTime'; E = { $_.properties.date } }, @{ N = 'ResourceName'; E = { $_.properties.resourceName } }, @{ N = 'ResourceGroup'; E = { $_.properties.resourceGroup } }, `
@{ N = 'CostCenter'; E = { $_.tags."cost-center" } }, @{ N = 'Project'; E = { $_.tags."project" } }, @{ N = 'Environment'; E = { $_.tags."environment" } }, @{ N = 'ResourceLocation'; E = { $_.properties.resourceLocation } }, 
@{ N = 'ConsumedService'; E = { $_.properties.consumedService } }, `
@{ N = 'Product'; E = { $_.properties.product } }, @{ N = 'Quantity'; E = { $_.properties.quantity } }, @{ N = 'UnitOfMeasure'; E = { $_.properties.meterDetails.unitOfMeasure } }, `
@{ N = 'UnitPrice'; E = { $_.properties.UnitPrice } }, @{ N = 'Cost'; E = { $_.properties.Cost } }, @{ N = 'Currency'; E = { $_.properties.billingCurrency } }, `
@{ N = 'PartNumber'; E = { $_.properties.partNumber } }, @{ N = 'MeterId'; E = { $_.properties.meterId } }

# Group by project tag + month

$projectGroup = $reportresult | Select-Object Project, Cost |  Group-Object Project | ForEach-Object {
    New-Object -Type PSObject -Property @{
        'BillingPeriod' = $YearMonth
        'Project'       = $_.Group | Select-Object -Expand Project -First 1
        'NOK'           = ($_.Group | Measure-Object Cost -Sum).Sum
    }
}  | Sort-Object NOK -Descending

# Group by rg + month

$rgGroup = $reportresult | Select-Object resourceGroup, Cost, ResourceLocation |  Group-Object resourceGroup | ForEach-Object {
    New-Object -Type PSObject -Property @{
        'BillingPeriod'    = $YearMonth
        'ResourceGroup'    = $_.Group | Select-Object -Expand ResourceGroup -First 1
        'NOK'              = ($_.Group | Measure-Object Cost -Sum).Sum
        'ResourceLocation' = $_.Group | Select-Object -Expand ResourceLocation -First 1
    }
}  | Sort-Object NOK -Descending

# Group by resourceName + month

$resGrouping = $reportresult | Select-Object ResourceName, ResourceGroup, ResourceLocation, ConsumedService, Cost |  Group-Object ResourceName | ForEach-Object {
    New-Object -Type PSObject -Property @{
        'BillingPeriod'    = $YearMonth
        'ResourceName'     = $_.Group | Select-Object -Expand ResourceName -First 1
        'NOK'              = ($_.Group | Measure-Object Cost -Sum).Sum
        'ServiceNamespace' = $_.Group  | Select-Object -Expand ConsumedService -First 1
        'ResourceLocation' = $_.Group  | Select-Object -Expand ResourceLocation -First 1
        'ResourceGroup'    = $_.Group  | Select-Object -Expand ResourceGroup -First 1
    }
} | Sort-Object NOK -Descending

# Export to File

$xlParams = @{WorkSheet = $ws; Bold = $true; FontSize = 16 }
$rawDataSheet = "Raw consumption data"
$groupingSheet = "By project tag"
$groupingSheet2 = "By resource group"
$groupingSheet3 = "By resourcename"

$excel2 = $projectGroup | Export-Excel -WorksheetName $groupingSheet -Path $ExcelFile -AutoSize -TableName Table1 -StartRow 15 -PassThru
$ws = $excel2.Workbook.Worksheets[$groupingSheet]
Set-Format -Range A1  -Value "Script run at: $($Date)" @xlParams -Worksheet $ws
Set-Format -Range A4  -Value "The script covers all subscriptions" @xlParams -Worksheet $ws
Set-Format -Range A13  -Value "Cost grouped by project tag" @xlParams -Worksheet $ws
Close-ExcelPackage $excel2

$excel0 = $rgGroup | Export-Excel -WorksheetName $groupingSheet2 -Path $ExcelFile -AutoSize -TableName Table2 -StartRow 15 -PassThru
$ws = $excel0.Workbook.Worksheets[$groupingSheet2]
Set-Format -Range A13  -Value "Cost grouped by resource group" @xlParams -Worksheet $ws
Close-ExcelPackage $excel0

$excel3 = $resGrouping | Export-Excel -WorksheetName $groupingSheet3 -Path $ExcelFile -AutoSize -TableName Table3 -StartRow 15 -PassThru
$ws = $excel3.Workbook.Worksheets[$groupingSheet3]
Set-Format -Range A13  -Value "Cost grouped by resource name" @xlParams -Worksheet $ws
Close-ExcelPackage $excel3

$excel1 = $reportResult | Export-Excel -WorksheetName $rawDataSheet -Path $ExcelFile -AutoSize -TableName Table4 -StartRow 15 -PassThru
$ws = $excel1.Workbook.Worksheets[$rawDataSheet]
Close-ExcelPackage $excel1