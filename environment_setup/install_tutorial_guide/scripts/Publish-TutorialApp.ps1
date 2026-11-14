#requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [uri]$ApiBaseUri,
    [string]$OutputRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [switch]$DevelopmentOnly,
    [switch]$LocalPreview,
    [string]$SourceRevision,
    [string]$ManifestPath,
    [string]$VideoCatalogPath = (Join-Path $PSScriptRoot '..\catalog\videos.example.json'),
    [switch]$RequireComplete,
    [string]$ServiceApprovalReference,
    [string]$BuildWrapper = 'C:\Users\jostrm\source\repos\AsomRecordsAB.Base\tools\Invoke-AsomDotnet.ps1',
    [string]$InnoCompiler,
    [string]$ProprietaryLicensePath,
    [switch]$LicenseReviewApproved,
    [string]$SignToolPath,
    [ValidatePattern('^$|^[A-Fa-f0-9]{40}$')][string]$CertificateThumbprint,
    [uri]$TimestampUri,
    [switch]$SigningApproved,
    [switch]$ValidateOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$startedUtc = [datetime]::UtcNow
$watch = [Diagnostics.Stopwatch]::StartNew()
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content (Join-Path $root 'release-config.json') -Raw | ConvertFrom-Json
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot).TrimEnd('\')
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\')

function Assert-PublicHttps([uri]$Uri, [switch]$AllowInvalid) {
    if (-not $Uri.IsAbsoluteUri -or $Uri.Scheme -cne 'https' -or
        $Uri.UserInfo -or $Uri.Query -or $Uri.Fragment -or $Uri.IsLoopback -or
        $Uri.HostNameType -ne [UriHostNameType]::Dns -or -not $Uri.Host.Contains('.') -or
        $Uri.Host -match '(?i)(^|\.)(localhost|local|internal|test)$') {
        throw 'Endpoint must be public HTTPS DNS, without credentials, query, fragment or private address.'
    }
    if (-not $AllowInvalid -and $Uri.DnsSafeHost -match '(?i)\.invalid$') {
        throw '.invalid is a nonfunctional development placeholder, not a production endpoint.'
    }
}
if ($LocalPreview) {
    if (-not $DevelopmentOnly) { throw 'LocalPreview is permitted only with DevelopmentOnly; bundled guides are not confidential.' }
    if ($ApiBaseUri) { throw 'Choose LocalPreview or ApiBaseUri, not both.' }
} else {
    if (-not $ApiBaseUri) { throw 'Protected service mode requires ApiBaseUri.' }
    Assert-PublicHttps $ApiBaseUri -AllowInvalid:$DevelopmentOnly
}
$accessMode = if ($LocalPreview) { 'local-invitation-gate/nonconfidential-guides' } else { 'protected-service' }
if (-not $OutputRoot.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputRoot must be a child of this distribution directory; never target the app or saved build.'
}
if ($OutputRoot -notmatch '(?i)\\(artifacts|staging|private)(\\|$)') {
    throw 'OutputRoot must be inside an ignored artifacts, staging or private directory.'
}
if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) { throw 'SourceRoot does not exist.' }
$project = Join-Path $SourceRoot $config.project
if (-not (Test-Path -LiteralPath $project -PathType Leaf)) { throw "TutorialApp project missing: $project" }
$projectDirectory = Split-Path $project -Parent
$localVerifier = Join-Path $projectDirectory 'previewcode.local.json'
function Assert-LocalVerifier([string]$Path) {
    $document = $null
    try {
        $file = Get-Item -LiteralPath $Path
        if ($file.PSIsContainer -or $file.Length -gt 4096 -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid verifier file.' }
        $document = [Text.Json.JsonDocument]::Parse([string](Get-Content -LiteralPath $Path -Raw))
        $value = $document.RootElement
        $names = @($value.EnumerateObject() | ForEach-Object Name | Sort-Object)
        if (($names -join ',') -cne 'iterations,salt,schemaVersion,verifier' -or
            $value.GetProperty('schemaVersion').GetInt32() -ne 1 -or $value.GetProperty('iterations').GetInt32() -ne 210000 -or
            [Convert]::FromBase64String($value.GetProperty('salt').GetString()).Length -ne 16 -or
            [Convert]::FromBase64String($value.GetProperty('verifier').GetString()).Length -ne 64) { throw 'Invalid verifier schema.' }
    } catch { throw 'LocalPreview requires a valid salted previewcode.local.json verifier with no additional fields; contents are never logged.' }
    finally { if ($document) { $document.Dispose() } }
}
if ($LocalPreview) { Assert-LocalVerifier $localVerifier }
if (-not $ManifestPath) { $ManifestPath = Join-Path $SourceRoot $config.manifest }
$content = & (Join-Path $PSScriptRoot 'Validate-VideoCatalog.ps1') -CatalogPath $VideoCatalogPath -ManifestPath $ManifestPath -RequireComplete:$RequireComplete
if ($RequireComplete -and -not $ServiceApprovalReference) {
    throw 'RequireComplete needs an explicit ServiceApprovalReference for actual service/content approval.'
}
if (-not $DevelopmentOnly) {
    if (-not $SigningApproved -or -not $SignToolPath -or -not $CertificateThumbprint -or -not $TimestampUri) {
        throw 'Production signing requires explicit approval, configured signtool, certificate identity and trusted timestamp URL.'
    }
    Assert-PublicHttps $TimestampUri
    if (-not $ProprietaryLicensePath -or -not $LicenseReviewApproved) {
        throw 'Production requires the approved proprietary license and completed third-party license review.'
    }
    if (-not $RequireComplete -or -not $ServiceApprovalReference) {
        throw 'Production delivery requires approved complete service content; empty examples are never a delivery.'
    }
}
$releaseDirectory = Join-Path $OutputRoot "releases\v$Version"
if (Test-Path -LiteralPath $releaseDirectory) { throw "Version already exists; preserve it and select a new version/output root: $releaseDirectory" }
$suffix = if ($DevelopmentOnly) { '-development-only' } else { '' }
$assetName = "ESAIF.TutorialApp-$Version-win-x64$suffix-setup"
if (-not $InnoCompiler) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $InnoCompiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if ($ValidateOnly) {
    [pscustomobject]@{
        Status = 'ValidatedNoBuild'; DevelopmentOnly = [bool]$DevelopmentOnly
        LocalPreview = [bool]$LocalPreview; AccessMode = $accessMode
        Version = $Version; AssetName = "$assetName.exe"; ContentComplete = $content.Complete
        BuildWrapperAvailable = (Test-Path -LiteralPath $BuildWrapper)
        InnoCompilerAvailable = [bool]$InnoCompiler; SourceRevisionClaim = $SourceRevision
        Note = 'No build, signing, installer, media verification or publication performed.'
    }
    return
}
foreach ($tool in @($BuildWrapper, $InnoCompiler)) {
    if (-not $tool -or -not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw 'Build wrapper and Inno compiler must already be installed; no automatic download.' }
}
if ($ProprietaryLicensePath -and -not (Test-Path -LiteralPath $ProprietaryLicensePath -PathType Leaf)) { throw 'Proprietary license file missing.' }
if (-not $DevelopmentOnly -and -not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) { throw 'Configured signtool missing.' }
if ((Get-Content $project -Raw) -notmatch 'TutorialAuthoring') {
    throw 'Client protected distribution mode has not been integrated; do not publish bundled authoring assets.'
}
if ($LocalPreview -and (Get-Content $project -Raw) -notmatch 'TutorialLocalPreview') {
    throw 'Client local invitation mode has not been integrated.'
}

function Get-OwnedProjects([string]$Entry) {
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $queue = [Collections.Generic.Queue[string]]::new()
    $queue.Enqueue($Entry)
    while ($queue.Count) {
        $path = [IO.Path]::GetFullPath($queue.Dequeue())
        if (-not $seen.Add($path)) { continue }
        if (-not (Test-Path -LiteralPath $path)) { throw "Referenced project missing: $path" }
        $path
        [xml]$xml = Get-Content -LiteralPath $path -Raw
        foreach ($reference in $xml.SelectNodes('//ProjectReference[@Include]')) {
            $include = $reference.GetAttribute('Include')
            if ($include -match '\$\(') { throw "Resolve dynamic ProjectReference explicitly before publishing: $include" }
            $queue.Enqueue([IO.Path]::GetFullPath((Join-Path (Split-Path $path -Parent) $include)))
        }
    }
}
$projects = @(Get-OwnedProjects $project)
$sourceParent = Split-Path $SourceRoot -Parent
foreach ($ownedProject in $projects) {
    if (-not $ownedProject.StartsWith($sourceParent + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Referenced source is outside the configured path-map root: $ownedProject"
    }
}
function Get-SourceState {
    $files = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $repositories = @{}
    foreach ($ownedProject in $projects) {
        $directory = Split-Path $ownedProject -Parent
        $relativeRoot = [IO.Path]::GetRelativePath($sourceParent, $directory).Split('\')[0]
        $repoRoot = Join-Path $sourceParent $relativeRoot
        if ($repositories.ContainsKey($relativeRoot)) { continue }
        $head = & git -C $repoRoot rev-parse HEAD 2>$null
        $gitOk = $LASTEXITCODE -eq 0
        $status = @(if ($gitOk) { & git -C $repoRoot status --porcelain --untracked-files=normal 2>$null } else { 'not-a-git-checkout' })
        $repositories[$relativeRoot] = @{
            Head = if ($gitOk) { "$head".Trim() } else { $null }
            Dirty = $status.Count -gt 0
            Status = $status
        }
        $pending = [Collections.Generic.Queue[string]]::new()
        $pending.Enqueue($repoRoot)
        while ($pending.Count) {
            foreach ($item in Get-ChildItem -LiteralPath $pending.Dequeue() -Force) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Source reparse point must be reviewed: $($item.FullName)" }
                if ($item.PSIsContainer) {
                    if ($item.Name -notin @('.git', '.vs', 'bin', 'obj', 'artifacts', 'last-successful-build', 'node_modules', '.venv', '__pycache__')) { $pending.Enqueue($item.FullName) }
                } else { [void]$files.Add($item.FullName) }
            }
        }
    }
    $rows = foreach ($file in @($files | Sort-Object)) {
        "$([IO.Path]::GetRelativePath($sourceParent, $file))`t$((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash)"
    }
    $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes(($rows -join "`n")))).ToLowerInvariant()
    @{ Fingerprint = $hash; FileCount = $files.Count; Repositories = $repositories; Files = $rows }
}
$before = Get-SourceState
if (@($before.Repositories.Values | Where-Object Dirty).Count) { Write-Warning 'Building dirty/local source. Fingerprint, not HEAD, identifies the input; no dirty-state-only rejection.' }
if ($SourceRevision -and $SourceRevision -notin @($before.Repositories.Values.Head)) {
    Write-Warning 'SourceRevision claim differs from observed HEAD values; recorded as a claim, not substituted for the source fingerprint.'
}
$runRoot = Join-Path $OutputRoot ('staging\' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $runRoot 'payload'
$private = Join-Path $runRoot 'private'
$buildOutput = Join-Path $private 'build'
$candidate = Join-Path $runRoot 'release'
New-Item $payload, $private, $candidate -ItemType Directory -Force | Out-Null
$before | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $private 'source-state.json') -Encoding utf8NoBOM
$completed = $false
$alias = $null
$subst = Join-Path $env:SystemRoot 'System32\subst.exe'
try {
    # Both the Windows XAML compiler and Inno require short staging paths.
    $occupied = @([IO.Directory]::GetLogicalDrives() | ForEach-Object { $_.Substring(0, 1) })
    $occupied += @(Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Name)
    $occupied += @(Get-ChildItem 'HKCU:\Network' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty PSChildName)
    $letter = 90..68 | ForEach-Object { ([char]$_).ToString() } | Where-Object { $_ -notin $occupied } | Select-Object -First 1
    if (-not $letter) { throw 'No unused drive alias for isolated build staging.' }
    $alias = "${letter}:"
    & $subst $alias $runRoot
    if ($LASTEXITCODE -ne 0) { $alias = $null; throw 'Could not create isolated build staging alias.' }
    # The shared wrapper owns the build mutex. Invoke in a child process because it exits.
    $buildArgs = @(
        'publish', $project,
        '-c', 'Release', '-f', $config.targetFramework, '-r', 'win-x64', '--self-contained', 'true',
        '-o', "$alias\payload", '--artifacts-path', "$alias\private\build",
        '-p:SelfContained=true', '-p:WindowsAppSDKSelfContained=true', '-p:TutorialAuthoring=false',
        $(if ($LocalPreview) { '-p:TutorialLocalPreview=true' } else { '-p:TutorialLocalPreview=false' }),
        "-p:ApplicationDisplayVersion=$Version", "-p:Version=$Version",
        '-p:DebugType=portable', '-p:DebugSymbols=true', '-p:Deterministic=true',
        '-p:ContinuousIntegrationBuild=true', "-p:PathMap=$sourceParent=C:\_source%2C$runRoot=C:\_build%2C$alias\=C:\_build\",
        '-p:EmbedUntrackedSources=false', '-p:PublishRepositoryUrl=false', '-nologo', '-v:minimal'
    )
    $quotedArgs = @($buildArgs | ForEach-Object { "'" + $_.Replace("'", "''") + "'" })
    $invocation = "& '" + $BuildWrapper.Replace("'", "''") + "' -DotnetArguments @(" + ($quotedArgs -join ',') + ')'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($invocation))
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -EncodedCommand $encoded *> (Join-Path $private 'publish.log')
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed; inspect private log: $private\publish.log" }
    $after = Get-SourceState
    if ($before.Fingerprint -ne $after.Fingerprint) { Write-Warning 'Source changed during publish; both fingerprints are recorded for review. Inspect the built payload before distribution.' }
    if (-not (Test-Path (Join-Path $payload 'ESAIF.TutorialApp.exe'))) { throw 'Native app executable missing from publish.' }
    foreach ($pdb in Get-ChildItem $payload -Filter '*.pdb' -Recurse -File) {
        $relative = [IO.Path]::GetRelativePath($payload, $pdb.FullName)
        $destination = Join-Path $private "symbols\$relative"
        New-Item (Split-Path $destination -Parent) -ItemType Directory -Force | Out-Null
        Move-Item -LiteralPath $pdb.FullName -Destination $destination
    }
    foreach ($item in Get-ChildItem $payload -Recurse -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Payload reparse points are forbidden.' }
        $relative = [IO.Path]::GetRelativePath($payload, $item.FullName)
        $localAsset = $LocalPreview -and (
            $relative -in @('Tutorials', 'tutorialcatalog.json', 'previewcode.local.json') -or
            ($relative.StartsWith('Tutorials\', [StringComparison]::OrdinalIgnoreCase) -and
                ($item.PSIsContainer -or $item.Extension -in @('.json', '.md', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.py'))))
        if ($item.Name -match '(?i)^(\.git|.*PreviewApi.*|tutorialsettings.*\.json|appsettings.*\.json|videos.*\.json|\.env.*|.*\.(pfx|p12|key|pem|mp4|mov|mkv|webm|srt|vtt|pdb))$' -or
            ($item.Name -match '(?i)^previewcode.*\.json$' -and (-not $LocalPreview -or $relative -ine 'previewcode.local.json')) -or
            (-not $localAsset -and $item.Name -match '(?i)^(Tutorials|tutorialcatalog\.json|.*\.py)$')) {
            throw "Forbidden content/private asset in payload: $($item.Name)"
        }
        if ($LocalPreview -and $relative.StartsWith('Tutorials\', [StringComparison]::OrdinalIgnoreCase) -and -not $localAsset) {
            throw 'Unexpected asset type in local tutorial payload.'
        }
        if ($localAsset -and -not $item.PSIsContainer) {
            $sourceAsset = Join-Path $projectDirectory $relative
            if (-not (Test-Path -LiteralPath $sourceAsset -PathType Leaf) -or
                (Get-FileHash -LiteralPath $sourceAsset).Hash -ne (Get-FileHash -LiteralPath $item.FullName).Hash) {
                throw 'Local guide/verifier payload differs from the fingerprinted source.'
            }
        }
    }
    if ($LocalPreview) {
        Assert-LocalVerifier (Join-Path $payload 'previewcode.local.json')
        $guideRoot = Join-Path $projectDirectory 'Tutorials'
        if (-not (Test-Path $guideRoot -PathType Container)) { throw 'Local tutorial guides missing from source.' }
        $expectedAssets = @(Get-ChildItem $guideRoot -Recurse -File)
        $expectedAssets += Get-Item (Join-Path $projectDirectory 'tutorialcatalog.json')
        foreach ($asset in $expectedAssets) {
            if (-not (Test-Path -LiteralPath (Join-Path $payload ([IO.Path]::GetRelativePath($projectDirectory, $asset.FullName))) -PathType Leaf)) {
                throw 'Local tutorial guide/catalog missing from payload.'
            }
        }
        $endpointSettings = Join-Path $payload 'previewsettings.json'
        if (Test-Path $endpointSettings) { Remove-Item -LiteralPath $endpointSettings }
    } else {
        @{ PreviewApiBaseUri = $ApiBaseUri.AbsoluteUri } | ConvertTo-Json | Set-Content (Join-Path $payload 'previewsettings.json') -Encoding utf8NoBOM
    }
    Copy-Item (Join-Path $root 'SUPPORT.txt') $payload
    if ($ProprietaryLicensePath) {
        Copy-Item -LiteralPath $ProprietaryLicensePath -Destination (Join-Path $payload 'PROPRIETARY-LICENSE.txt')
    } else {
        'PROPRIETARY DEVELOPMENT PREVIEW. Copyright (c) 2026 Asom Records AB. All rights reserved. No distribution or use license is granted. Owner-approved full terms required before production.' |
            Set-Content (Join-Path $payload 'PROPRIETARY-LICENSE.txt') -Encoding utf8NoBOM
    }
    $licenseRoot = Join-Path $payload 'Licenses\NuGet'
    New-Item $licenseRoot -ItemType Directory -Force | Out-Null
    $packages = @{}
    foreach ($ownedProject in $projects) {
        $assetsPath = Join-Path $buildOutput "obj\$([IO.Path]::GetFileNameWithoutExtension($ownedProject))\project.assets.json"
        if (-not (Test-Path $assetsPath)) { throw "Cannot inventory dependencies: missing $assetsPath" }
        $assets = Get-Content $assetsPath -Raw | ConvertFrom-Json -AsHashtable
        foreach ($entry in $assets.libraries.GetEnumerator()) {
            if ($entry.Value.type -ne 'package' -or $packages.ContainsKey($entry.Key)) { continue }
            $packageDirectory = $null
            foreach ($folder in $assets.packageFolders.Keys) {
                $possible = Join-Path $folder $entry.Value.path
                if (Test-Path $possible) { $packageDirectory = $possible; break }
            }
            if (-not $packageDirectory) { throw "NuGet cache unavailable for notices: $($entry.Key)" }
            $nuspec = Get-ChildItem $packageDirectory -Filter '*.nuspec' -File | Select-Object -First 1
            if (-not $nuspec) { throw "NuGet metadata missing: $($entry.Key)" }
            [xml]$metadata = Get-Content $nuspec.FullName -Raw
            $licenseNode = $metadata.SelectSingleNode('//*[local-name()="metadata"]/*[local-name()="license"]')
            $urlNode = $metadata.SelectSingleNode('//*[local-name()="metadata"]/*[local-name()="licenseUrl"]')
            $licenseType = if ($licenseNode) { $licenseNode.GetAttribute('type') } else { 'unknown' }
            $licenseValue = if ($licenseNode) { $licenseNode.InnerText } else { '' }
            $destination = Join-Path $licenseRoot ($entry.Key.Replace('/', '\'))
            New-Item $destination -ItemType Directory -Force | Out-Null
            $licenseFiles = @(Get-ChildItem $packageDirectory -File -Recurse | Where-Object {
                $_.Name -match '(?i)^(license|licence|copying|notice|third[-_. ]?party[-_. ]?notices?)(\..*|[-_ ].*)?$'
            })
            if ($licenseType -eq 'file') {
                $declared = [IO.Path]::GetFullPath((Join-Path $packageDirectory $licenseValue))
                if (-not $declared.StartsWith($packageDirectory.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path $declared)) { throw 'Invalid/missing NuGet license file.' }
                $licenseFiles += Get-Item $declared
            }
            foreach ($file in @($licenseFiles | Sort-Object FullName -Unique)) {
                $relative = [IO.Path]::GetRelativePath($packageDirectory, $file.FullName)
                $copyTo = Join-Path $destination $relative
                New-Item (Split-Path $copyTo -Parent) -ItemType Directory -Force | Out-Null
                Copy-Item -LiteralPath $file.FullName -Destination $copyTo
            }
            $packages[$entry.Key] = @{
                Package = $entry.Key; LicenseType = $licenseType; License = $licenseValue
                LicenseUrl = if ($urlNode) { $urlNode.InnerText } else { $null }
                IncludedTextCount = @($licenseFiles | Sort-Object FullName -Unique).Count
                ReviewRequired = $true
            }
        }
    }
    @($packages.Values | Sort-Object Package) | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $payload 'Licenses\nuget-inventory.json') -Encoding utf8NoBOM
    $fontRoot = Join-Path (Split-Path $project -Parent) 'Resources\Fonts'
    $fonts = @(if (Test-Path $fontRoot) {
        Get-ChildItem $fontRoot -File | Where-Object Extension -In @('.ttf', '.otf') | ForEach-Object {
            @{ name = $_.Name; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); reviewRequired = $true }
        }
    })
    ConvertTo-Json -InputObject $fonts -Depth 5 | Set-Content (Join-Path $payload 'Licenses\font-inventory.json') -Encoding utf8NoBOM
    Copy-Item (Join-Path $root 'installer\licenses') (Join-Path $payload 'Licenses\Fonts') -Recurse
    @(
        'THIRD-PARTY NOTICES — dependency inventory, not legal certification.'
        'See Licenses\NuGet for available package license/notice texts and Licenses\nuget-inventory.json for expressions/URLs.'
        'Runtime/SDK native components may have separate bundled notices. Retain them. Missing texts and platform redistribution terms need owner review.'
        'See Licenses\font-inventory.json for actual application font filenames/hashes and Licenses\Fonts for observed OpenSans attribution and its Apache-2.0 license. Full license review remains required.'
        "License review explicitly approved: $([bool]$LicenseReviewApproved)"
        ''
        @($packages.Values | Sort-Object Package | ForEach-Object { "$($_.Package): $($_.LicenseType) $($_.License) $($_.LicenseUrl)" })
    ) | Set-Content (Join-Path $payload 'THIRD-PARTY-NOTICES.txt') -Encoding utf8NoBOM
    $ownedBinaries = @(Get-ChildItem $payload -File -Recurse | Where-Object { $_.Extension -in @('.dll', '.exe') -and $_.BaseName -match '^(ESAIF\.|AsomRecordsAB\.)' })
    $textFiles = @(Get-ChildItem $payload -File -Recurse | Where-Object { $_.Extension -in @('.json', '.xml', '.config', '.txt', '.md', '.yaml', '.yml', '.ps1', '.py', '.svg') })
    foreach ($binary in @($ownedBinaries) + @($textFiles)) {
        $bytes = [IO.File]::ReadAllBytes($binary.FullName)
        $ascii = [Text.Encoding]::UTF8.GetString($bytes)
        $wide = [Text.Encoding]::Unicode.GetString($bytes)
        foreach ($path in @($SourceRoot, $sourceParent, $env:USERPROFILE, $runRoot)) {
            if ($ascii.Contains($path, [StringComparison]::OrdinalIgnoreCase) -or $wide.Contains($path, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Absolute development path detected in payload: $($binary.Name)"
            }
        }
        $secretPattern = '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AccountKey=[A-Za-z0-9+/]{30,}={0,2}|[?&]sig=[A-Za-z0-9%+/]{25,}|\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})\b'
        if ($ascii -match $secretPattern -or $wide -match $secretPattern) {
            throw "Possible credential detected in payload: $($binary.Name); inspect privately, never publish."
        }
    }
    function Assert-Signed([string]$Path) {
        $signature = Get-AuthenticodeSignature -LiteralPath $Path
        if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
            $signature.SignerCertificate.Thumbprint -ine $CertificateThumbprint -or -not $signature.TimeStamperCertificate) {
            throw "Publisher signature or trusted timestamp invalid: $Path"
        }
    }
    if (-not $DevelopmentOnly) {
        foreach ($binary in $ownedBinaries) {
            & $SignToolPath sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUri.AbsoluteUri /td SHA256 $binary.FullName *> (Join-Path $private 'signing.log')
            if ($LASTEXITCODE -ne 0) { throw "Signing failed: $($binary.Name)" }
            Assert-Signed $binary.FullName
        }
    }
    & {
        Copy-Item (Join-Path $root 'installer\ESAIF.TutorialApp.iss') (Join-Path $runRoot 'installer.iss')
        Copy-Item (Join-Path $root 'SUPPORT.txt') (Join-Path $runRoot 'SUPPORT.txt')
        $innoArgs = @('/Qp', "/DPayload=$alias\payload", "/DAppVersion=$Version", "/DOutputName=$assetName", "/DOutputDirectory=$alias\release",
            "/DProductId=$($config.appId)", "/DSupportFile=$alias\SUPPORT.txt")
        if ($DevelopmentOnly) { $innoArgs += '/DDevelopmentOnly=1' } else {
            $innoArgs += '/DSignedBuild=1'
            $signCommand = '$q' + $SignToolPath + '$q sign /sha1 ' + $CertificateThumbprint + ' /fd SHA256 /tr ' + $TimestampUri.AbsoluteUri + ' /td SHA256 $f'
            $innoArgs += "/STutorialSign=$signCommand"
        }
        if ($LocalPreview) { $innoArgs += '/DLocalPreview=1' }
        $innoArgs += "$alias\installer.iss"
        & $InnoCompiler @innoArgs *> (Join-Path $private 'installer.log')
        if ($LASTEXITCODE -ne 0) { throw "Inno compilation failed; inspect private log: $private\installer.log" }
    }
    $installer = Join-Path $candidate "$assetName.exe"
    if (-not (Test-Path $installer)) { throw 'Installer EXE missing.' }
    if (-not $DevelopmentOnly) { Assert-Signed $installer }
    if (Get-ChildItem $candidate -File | Where-Object Length -GE $config.maximumAssetBytesExclusive) {
        throw 'Every GitHub Release asset must be strictly smaller than 2 GiB; no Git history binary upload.'
    }
    $payloadHashes = @(Get-ChildItem $payload -Recurse -File | Sort-Object FullName | ForEach-Object {
        @{ Path = [IO.Path]::GetRelativePath($payload, $_.FullName); Sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); Bytes = $_.Length }
    })
    $payloadHashes | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $candidate 'payload-sha256.json') -Encoding utf8NoBOM
    $manifest = @{
        schemaVersion = 1; product = $config.product; version = $Version; developmentOnly = [bool]$DevelopmentOnly
        status = 'local-built-not-published'; releaseTag = "$($config.releaseTagPrefix)$Version"
        releaseUrl = "$($config.repositoryUrl)/releases/tag/$($config.releaseTagPrefix)$Version"
        startedUtc = $startedUtc.ToString('o'); createdUtc = [datetime]::UtcNow.ToString('o')
        apiBaseUri = if ($ApiBaseUri) { $ApiBaseUri.AbsoluteUri } else { $null }
        accessMode = $accessMode
        source = @{
            revisionClaim = $SourceRevision; fingerprintSha256 = $before.Fingerprint; fileCount = $before.FileCount
            afterFingerprintSha256 = $after.Fingerprint; changedDuringPublish = $before.Fingerprint -ne $after.Fingerprint
            repositories = @($before.Repositories.GetEnumerator() | ForEach-Object { @{ name = $_.Key; head = $_.Value.Head; dirty = $_.Value.Dirty } })
            interpretation = 'Fingerprint covers local owned source trees, including dirty inputs; HEAD alone is not the build identity.'
        }
        content = @{ completeMetadata = $content.Complete; recordingsVerified = $false; liveMappingsPublished = $false; completenessRequired = [bool]$RequireComplete; serviceApprovalReference = $ServiceApprovalReference; tutorialId = $content.TutorialId; catalogRevision = $content.CatalogRevision; bundled = [bool]$LocalPreview }
        signing = @{ signed = -not [bool]$DevelopmentOnly; authenticodeStatus = [string](Get-AuthenticodeSignature -LiteralPath $installer).Status; certificateThumbprint = $CertificateThumbprint; timestampUri = if ($TimestampUri) { $TimestampUri.AbsoluteUri } else { $null }; uninstallerSigningRequired = -not [bool]$DevelopmentOnly }
        licenses = @{ reviewApproved = [bool]$LicenseReviewApproved; packageCount = $packages.Count; certified = $false }
        artifacts = @(@{ name = "$assetName.exe"; localPath = Join-Path $releaseDirectory "$assetName.exe"; bytes = (Get-Item $installer).Length; sha256 = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant() })
        elapsedSeconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
    }
    $manifest | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $candidate 'release.json') -Encoding utf8NoBOM
    @(
        "# ESAIF Tutorials $Version$suffix"
        ''
        'Local candidate only; not uploaded, published, installed or deployed.'
        "Source fingerprint: $($before.Fingerprint)"
        "Catalog metadata complete: $($content.Complete). Content approval: $ServiceApprovalReference"
        "Access mode: $accessMode"
        $(if ($LocalPreview) {
            'Trusted-cohort invitation gate only: bundled guides are extractable and not confidential. The salted verifier is bundled; no server authorization, revocation or expiry is provided. Recordings remain unavailable; this is not a full video rollout.'
        } else { 'Protected materials are service-delivered, not bundled.' })
        'See SUPPORT.txt for platform, codec, state and rollback policy.'
    ) | Set-Content (Join-Path $candidate 'release-notes.md') -Encoding utf8NoBOM
    Copy-Item (Join-Path $root 'SUPPORT.txt') $candidate
    Get-ChildItem $candidate -File | Sort-Object Name | ForEach-Object {
        "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())  $($_.Name)"
    } | Set-Content (Join-Path $candidate 'SHA256SUMS.txt') -Encoding utf8NoBOM
    if (Get-ChildItem $candidate -File | Where-Object Length -GE $config.maximumAssetBytesExclusive) {
        throw 'Every finalized release asset must be strictly smaller than 2 GiB.'
    }
    New-Item (Split-Path $releaseDirectory -Parent) -ItemType Directory -Force | Out-Null
    [IO.Directory]::Move($candidate, $releaseDirectory)
    $completed = $true
    [pscustomobject]@{ Status = 'LocalBuiltNotPublished'; ReleaseDirectory = $releaseDirectory; PrivateBuildDirectory = $runRoot; ElapsedSeconds = [math]::Round($watch.Elapsed.TotalSeconds, 2) }
} finally {
    if ($alias) { & $subst $alias /D | Out-Null }
    if (-not $completed) { Write-Warning "Failed candidate remains isolated at $runRoot; existing releases and last-successful-build were not replaced." }
}
