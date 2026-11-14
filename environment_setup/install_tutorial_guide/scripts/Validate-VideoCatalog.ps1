#requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CatalogPath,
    [Parameter(Mandatory)][string]$ManifestPath,
    [string]$SchemaPath = (Join-Path $PSScriptRoot '..\catalog\videos.schema.json'),
    [switch]$RequireComplete
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$json = Get-Content -LiteralPath $CatalogPath -Raw
if (-not (Test-Json -Json $json -SchemaFile $SchemaPath -ErrorAction Stop)) {
    throw 'Video catalog does not satisfy videos.schema.json.'
}
$catalog = $json | ConvertFrom-Json
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($catalog.tutorialId -cne $manifest.id) { throw 'Catalog tutorialId does not match the selected manifest.' }
$coreIds = @(1..6 | ForEach-Object { "scenario-$_" })
$scenarioIds = @($manifest.scenarios | ForEach-Object { $_.id })
foreach ($id in $coreIds) {
    if (@($scenarioIds | Where-Object { $_ -ceq $id }).Count -ne 1) {
        throw "Selected manifest must contain exactly one '$id'."
    }
}
$videoIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$orders = [Collections.Generic.HashSet[int]]::new()
$represented = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$titleMismatches = @()
foreach ($video in $catalog.videos) {
    if ($video.scenarioId -cnotin $scenarioIds) { throw "Scenario absent from selected manifest: $($video.scenarioId)" }
    if (-not $videoIds.Add($video.videoId)) { throw "Duplicate videoId: $($video.videoId)" }
    if (-not $orders.Add($video.displayOrder)) {
        throw "Duplicate catalog displayOrder: $($video.displayOrder)"
    }
    if (-not $represented.Add($video.scenarioId)) {
        throw "Scenario '$($video.scenarioId)' can have only one primary recording."
    }
    if ($video.PSObject.Properties['durationSeconds'] -and -not [double]::IsFinite($video.durationSeconds)) {
        throw 'durationSeconds must be positive and finite.'
    }
    $scenario = $manifest.scenarios | Where-Object id -CEQ $video.scenarioId
    if ($video.title -cne $scenario.title) {
        $titleMismatches += $video.scenarioId
    }
}
$presentIds = @($catalog.videos | ForEach-Object { $_.scenarioId })
$missing = @($coreIds | Where-Object { $_ -cnotin $presentIds })
$complete = $missing.Count -eq 0 -and $titleMismatches.Count -eq 0
if ($RequireComplete -and -not $complete) {
    throw "Incomplete recording metadata: missing [$($missing -join ', ')]; titles do not exactly match selected tutorial [$($titleMismatches -join ', ')]."
}
[pscustomobject]@{
    Valid = $true
    Complete = $complete
    TutorialId = $catalog.tutorialId
    CatalogRevision = $catalog.catalogRevision
    VideoCount = @($catalog.videos).Count
    MissingScenarioIds = $missing
    MismatchedTitleScenarioIds = $titleMismatches
    MediaVerified = $false
    Note = 'Structural validation only; service approval, actual media and duration verification are separate requirements.'
}
