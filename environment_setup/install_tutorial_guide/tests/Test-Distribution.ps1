#requires -Version 7.4
[CmdletBinding()]
param([string]$SourceRoot, [string]$InnoCompiler, [switch]$ExercisePackaging)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$checks = 0
function Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:checks++
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $threw = $false
    try { & $Action | Out-Null } catch { $threw = $true }
    Assert $threw $Message
}
$watch = [Diagnostics.Stopwatch]::StartNew()
foreach ($file in @('scripts\Publish-TutorialApp.ps1', 'scripts\Validate-VideoCatalog.ps1',
    'catalog\videos.schema.json', 'catalog\videos.example.json', 'installer\ESAIF.TutorialApp.iss',
    'release-config.json', 'README.md', 'SUPPORT.txt')) {
    Assert (Test-Path (Join-Path $root $file)) "Required file: $file"
}
foreach ($file in Get-ChildItem (Join-Path $root 'scripts') -Filter '*.ps1') {
    $tokens = $null; $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    Assert ($errors.Count -eq 0) "PowerShell parses: $($file.Name): $errors"
}
$validate = Join-Path $root 'scripts\Validate-VideoCatalog.ps1'
$publish = Join-Path $root 'scripts\Publish-TutorialApp.ps1'
$work = Join-Path $PSScriptRoot ('.work-' + [guid]::NewGuid().ToString('N'))
New-Item $work -ItemType Directory | Out-Null
try {
    $manifestPath = Join-Path $work 'tutorial.json'
    $manifest = @{
        id = 'esaif-python-sdk-01'
        scenarios = @((Get-Content (Join-Path $root 'release-config.json') -Raw | ConvertFrom-Json).coreScenarios)
    }
    $manifest | ConvertTo-Json -Depth 10 | Set-Content $manifestPath
    $sample = Join-Path $root 'catalog\videos.example.json'
    $result = & $validate -CatalogPath $sample -ManifestPath $manifestPath
    Assert ($result.Valid -and -not $result.Complete) 'Empty sample valid, explicitly incomplete'
    Assert-Throws { & $validate -CatalogPath $sample -ManifestPath $manifestPath -RequireComplete } 'Empty sample not complete'
    $catalog = Get-Content $sample -Raw | ConvertFrom-Json -AsHashtable
    $catalog.videos = @(1..6 | ForEach-Object {
        @{ videoId = "synthetic-$_"; scenarioId = "scenario-$_"; title = $manifest.scenarios[$_ - 1].title; displayOrder = $_; mediaRef = "fixture-$_" }
    })
    $catalogPath = Join-Path $work 'fixture.json'
    function Save-Fixture { $catalog | ConvertTo-Json -Depth 10 | Set-Content $catalogPath }
    Save-Fixture
    Assert ((& $validate -CatalogPath $catalogPath -ManifestPath $manifestPath -RequireComplete).Complete) 'Six primary fixture entries complete structurally'
    $catalog.videos[0].mediaRef = 'https://example.invalid/video.mp4'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject media URLs'
    $catalog.videos[0].mediaRef = '..\private.mp4'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject media paths'
    $catalog.videos[0].mediaRef = 'fixture-1'
    $catalog.videos[0].scenarioId = 'scenario-99'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject unknown scenario'
    $catalog.videos[0].scenarioId = 'scenario-1'
    foreach ($order in @(0, -1, 101, 1.5)) {
        $catalog.videos[0].displayOrder = $order; Save-Fixture
        Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } "Reject displayOrder $order"
    }
    $catalog.videos[0].displayOrder = 2; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Orders unique across whole catalog'
    $catalog.videos[0].displayOrder = 100; Save-Fixture
    Assert ((& $validate -CatalogPath $catalogPath -ManifestPath $manifestPath -RequireComplete).Complete) 'Inclusive upper order boundary is valid'
    $catalog.videos[0].displayOrder = 1
    $catalog.videos[0].title = 'Scenario 1: Initial bootstrap'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath -RequireComplete } 'Reject alternate scenario title for complete selected tutorial'
    $catalog.videos[0].title = $manifest.scenarios[0].title
    $catalog.videos[1].videoId = 'synthetic-1'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject duplicate video identity'
    $catalog.videos[1].videoId = 'synthetic-2'
    $catalog.videos[1].scenarioId = 'scenario-1'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject two primary entries in one scenario'
    $catalog.videos[1].scenarioId = 'scenario-2'
    $catalog.videos[0].durationSeconds = -1; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject invalid duration'
    $catalog.videos[0].Remove('durationSeconds')
    foreach ($duration in @(0, [double]::PositiveInfinity, [double]::NaN)) {
        $catalog.videos[0].durationSeconds = $duration; Save-Fixture
        Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject zero/nonfinite duration'
    }
    $catalog.videos[0].Remove('durationSeconds')
    foreach ($field in @('mediaRef', 'posterMediaRef', 'captionMediaRef')) {
        $catalog.videos[0][$field] = 'not/an/opaque-id'; Save-Fixture
        Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } "Reject nonopaque $field"
        $catalog.videos[0].Remove($field)
    }
    $catalog.videos[0].mediaRef = 'fixture-1'
    $catalog.videos[0].secret = 'not-allowed'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Reject additional fields'
    $catalog.videos[0].Remove('secret')
    $catalog.tutorialId = 'other-tutorial'; Save-Fixture
    Assert-Throws { & $validate -CatalogPath $catalogPath -ManifestPath $manifestPath } 'Require selected tutorial identity'
    $gateSource = Join-Path $work 'gate-source'
    $gateProject = Join-Path $gateSource 'src\ESAIF.TutorialApp'
    New-Item $gateProject -ItemType Directory -Force | Out-Null
    '<Project><PropertyGroup><TutorialAuthoring>false</TutorialAuthoring><TutorialLocalPreview>false</TutorialLocalPreview></PropertyGroup></Project>' | Set-Content "$gateProject\ESAIF.TutorialApp.csproj"
    $gateArgs = @{
        SourceRoot = $gateSource; OutputRoot = Join-Path $work 'artifacts\gate'
        Version = '0.2.0'; DevelopmentOnly = $true; LocalPreview = $true
        ManifestPath = $manifestPath; ValidateOnly = $true
    }
    Assert-Throws { & $publish @gateArgs } 'Local mode requires an existing verifier'
    $verifier = @{
        schemaVersion = 1; iterations = 210000
        salt = [Convert]::ToBase64String([byte[]](1..16))
        verifier = [Convert]::ToBase64String([byte[]](1..64))
    }
    $verifierPath = Join-Path $gateProject 'previewcode.local.json'
    $verifier | ConvertTo-Json | Set-Content $verifierPath
    $localPreflight = & $publish @gateArgs
    Assert ($localPreflight.LocalPreview -and $localPreflight.AccessMode -eq 'local-invitation-gate/nonconfidential-guides') 'Local preflight needs no API endpoint and discloses nonconfidential guides'
    Assert (-not (Test-Path $gateArgs.OutputRoot)) 'Local validation creates no output'
    $gateArgs.DevelopmentOnly = $false
    Assert-Throws { & $publish @gateArgs } 'Local mode is forbidden without DevelopmentOnly'
    $gateArgs.DevelopmentOnly = $true
    $gateArgs.ApiBaseUri = 'https://preview.example.invalid/'
    Assert-Throws { & $publish @gateArgs } 'Reject ambiguous local plus API endpoint configuration'
    $gateArgs.Remove('ApiBaseUri')
    $gateArgs.LocalPreview = $false
    Assert-Throws { & $publish @gateArgs } 'Protected mode still requires API endpoint'
    $gateArgs.LocalPreview = $true
    foreach ($mutation in @('plaintext', 'schema', 'salt', 'verifier', 'iterations', 'string-iterations')) {
        $invalidVerifier = $verifier.Clone()
        switch ($mutation) {
            'plaintext' { $invalidVerifier.code = 'inert-test-value' }
            'schema' { $invalidVerifier.schemaVersion = 2 }
            'salt' { $invalidVerifier.salt = 'invalid' }
            'verifier' { $invalidVerifier.verifier = [Convert]::ToBase64String([byte[]](1..16)) }
            'iterations' { $invalidVerifier.iterations = 1 }
            'string-iterations' { $invalidVerifier.iterations = '210000' }
        }
        $invalidVerifier | ConvertTo-Json | Set-Content $verifierPath
        Assert-Throws { & $publish @gateArgs } "Reject invalid verifier $mutation"
    }
    $duplicateVerifier = ($verifier | ConvertTo-Json).Replace('"schemaVersion": 1', '"schemaVersion": 2, "schemaVersion": 1')
    $duplicateVerifier | Set-Content $verifierPath
    Assert-Throws { & $publish @gateArgs } 'Reject duplicate verifier fields rather than silently accepting the last value'
    $verifier | ConvertTo-Json | Set-Content $verifierPath
    if ($SourceRoot) {
        $args = @{
            SourceRoot = $SourceRoot; OutputRoot = (Join-Path $work 'artifacts')
            Version = '0.2.0'; ApiBaseUri = 'https://preview.example.invalid/'
            DevelopmentOnly = $true; ValidateOnly = $true
        }
        $preflight = & $publish @args
        Assert ($preflight.DevelopmentOnly -and $preflight.Status -eq 'ValidatedNoBuild') 'Offline preflight does not build'
        Assert (-not (Test-Path $args.OutputRoot)) 'Validation creates no output'
        foreach ($uri in @('http://preview.example.invalid/', 'https://localhost/', 'https://127.0.0.1/', 'https://10.1.1.1/', 'https://u:p@example.invalid/', 'https://example.invalid/?secret=x')) {
            $args.ApiBaseUri = $uri
            Assert-Throws { & $publish @args } "Reject unsafe API endpoint $uri"
        }
        $args.ApiBaseUri = 'https://preview.example.invalid/'
        $args.DevelopmentOnly = $false
        Assert-Throws { & $publish @args } 'Unsigned production is forbidden'
    }
    $iss = Get-Content (Join-Path $root 'installer\ESAIF.TutorialApp.iss') -Raw
    Assert ($iss -match 'PrivilegesRequired=lowest') 'Per-user installer'
    Assert ($iss -match 'MinVersion=10.0.22000') 'Windows 11 minimum'
    Assert ($iss -notmatch 'HasWebView2|WebView2 Runtime is required') 'No WebView2 dependency'
    Assert ($iss -notmatch '\[UninstallDelete\]') 'No user data deletion'
    Assert ($iss -match 'ALLOWDOWNGRADE') 'Explicit downgrade guard'
    Assert ($iss -match 'SignedUninstaller=yes') 'Production signs uninstaller'
    Assert ($iss -match 'CloseApplications=no') 'Installer does not terminate any running app'
    Assert ($iss -match 'DEVELOPMENT-ONLY') 'Development installer identifies itself visibly'
    Assert ($iss -match '#ifdef LocalPreview') 'Installer explicitly selects local payload exemptions'
    $script = Get-Content $publish -Raw
    Assert ($script -notmatch '&[^\r\n]*my-build') 'Never invokes saved-build wrapper'
    Assert ($script -match 'TutorialAuthoring=false') 'Protected publish mode'
    Assert ($script -match 'WindowsAppSDKSelfContained=true' -and $script -match 'SelfContained=true') 'Both runtime layers self-contained'
    Assert ($script -match '\-\-artifacts-path') 'Fresh project-separated build outputs, not stale source bin/obj'
    Assert ($script -match 'PreviewApiBaseUri =') 'Writes the actual public client configuration key'
    Assert ($script -notmatch 'gh release create|git push|az deployment') 'No remote publication'
    Assert ($script.IndexOf('& $subst $alias $runRoot') -lt $script.IndexOf('$buildArgs = @(')) 'Short staging paths established before Windows XAML compilation'
    if ($ExercisePackaging) {
        $fakeSource = Join-Path $work 'source\ESAIF.TutorialApp'
        $fakeProject = Join-Path $fakeSource 'src\ESAIF.TutorialApp'
        $packageDirectory = Join-Path $work 'packages\synthetic-notice\1.0.0'
        New-Item "$fakeProject\obj", "$fakeProject\Tutorials\esaif-python-sdk-01", $packageDirectory -ItemType Directory -Force | Out-Null
        '<Project><PropertyGroup><TutorialAuthoring>false</TutorialAuthoring><TutorialLocalPreview>false</TutorialLocalPreview></PropertyGroup></Project>' | Set-Content "$fakeProject\ESAIF.TutorialApp.csproj"
        $manifest | ConvertTo-Json -Depth 10 | Set-Content "$fakeProject\Tutorials\esaif-python-sdk-01\tutorial.json"
        'Inert guide fixture.' | Set-Content "$fakeProject\Tutorials\esaif-python-sdk-01\guide.md"
        '# Inert tutorial source example; never executed.' | Set-Content "$fakeProject\Tutorials\esaif-python-sdk-01\example.py"
        '{"tutorials":[]}' | Set-Content "$fakeProject\tutorialcatalog.json"
        $verifier | ConvertTo-Json | Set-Content "$fakeProject\previewcode.local.json"
        '<package><metadata><id>synthetic-notice</id><version>1.0.0</version><license type="expression">MIT</license></metadata></package>' | Set-Content "$packageDirectory\synthetic-notice.nuspec"
        'Synthetic fixture notice only; no real package content.' | Set-Content "$packageDirectory\LICENSE.txt"
        @{
            libraries = @{ 'synthetic-notice/1.0.0' = @{ type = 'package'; path = 'synthetic-notice\1.0.0' } }
            packageFolders = @{ (Join-Path $work 'packages') = @{} }
        } | ConvertTo-Json -Depth 10 | Set-Content "$fakeProject\obj\project.assets.json"
        $fakeWrapper = Join-Path $work 'fake-build.ps1'
        @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$DotnetArguments)
$out = $DotnetArguments[[Array]::IndexOf($DotnetArguments, '-o') + 1]
$build = $DotnetArguments[[Array]::IndexOf($DotnetArguments, '--artifacts-path') + 1]
$project = $DotnetArguments[1]
$local = $DotnetArguments -contains '-p:TutorialLocalPreview=true'
if (-not $local -and $DotnetArguments -notcontains '-p:TutorialLocalPreview=false') { throw 'Protected mode must explicitly disable implicit local configuration.' }
New-Item (Join-Path $build 'obj\ESAIF.TutorialApp') -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path (Split-Path $project) 'obj\project.assets.json') (Join-Path $build 'obj\ESAIF.TutorialApp\project.assets.json')
'INERT ACCEPTANCE FIXTURE - NOT AN EXECUTABLE' | Set-Content (Join-Path $out 'ESAIF.TutorialApp.exe')
'INERT SYMBOL FIXTURE' | Set-Content (Join-Path $out 'ESAIF.TutorialApp.pdb')
if ($local) {
    foreach ($asset in @('Tutorials', 'tutorialcatalog.json', 'previewcode.local.json')) {
        Copy-Item (Join-Path (Split-Path $project) $asset) $out -Recurse
    }
}
$modePath = Join-Path (Split-Path $project) 'fixture-mode.txt'
if (Test-Path $modePath) {
    switch ((Get-Content $modePath -Raw).Trim()) {
        'tutorial' { New-Item (Join-Path $out 'Tutorials') -ItemType Directory | Out-Null }
        'secret' { 'AccountKey=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' | Set-Content (Join-Path $out 'unexpected.json') }
        'source-path' { $project | Set-Content (Join-Path $out 'unexpected.json') }
        'api' { 'INERT API FIXTURE' | Set-Content (Join-Path $out 'ESAIF.TutorialApp.PreviewApi.dll') }
        'verifier' { Copy-Item (Join-Path (Split-Path $project) 'previewcode.local.json') $out }
        'nested-verifier' { Copy-Item (Join-Path (Split-Path $project) 'previewcode.local.json') (Join-Path $out 'Tutorials\previewcode.local.json') }
        'tampered-verifier' { '{"code":"inert-test-value"}' | Set-Content (Join-Path $out 'previewcode.local.json') }
        'media' { 'INERT MEDIA FIXTURE' | Set-Content (Join-Path $out 'Tutorials\example.mp4') }
        'missing-guide' { Remove-Item (Join-Path $out 'Tutorials') -Recurse -Force }
    }
}
exit 0
'@ | Set-Content $fakeWrapper
        $fakeCompiler = Join-Path $work 'fake-inno.ps1'
        @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$out = ($Arguments | Where-Object { $_ -like '/DOutputDirectory=*' }).Substring('/DOutputDirectory='.Length)
$name = ($Arguments | Where-Object { $_ -like '/DOutputName=*' }).Substring('/DOutputName='.Length)
'INERT ACCEPTANCE FIXTURE - NOT AN INSTALLER' | Set-Content (Join-Path $out "$name.exe")
'@ | Set-Content $fakeCompiler
        $packageArgs = @{
            SourceRoot = $fakeSource; OutputRoot = Join-Path $work 'artifacts\fixture'
            Version = '0.2.0'; ApiBaseUri = 'https://preview.example.invalid/'
            DevelopmentOnly = $true; BuildWrapper = $fakeWrapper; InnoCompiler = $fakeCompiler
        }
        try { $built = & $publish @packageArgs } catch {
            Get-ChildItem (Join-Path $work 'artifacts\fixture') -Filter 'publish.log' -Recurse | ForEach-Object { Get-Content $_.FullName | Write-Host }
            throw
        }
        Assert ($built.Status -eq 'LocalBuiltNotPublished') 'Synthetic packaging chain completes'
        $record = Get-Content (Join-Path $built.ReleaseDirectory 'release.json') -Raw | ConvertFrom-Json
        Assert ($record.developmentOnly -and -not $record.signing.signed) 'Unsigned candidate labeled development-only'
        Assert ($record.accessMode -eq 'protected-service' -and -not $record.content.bundled) 'Protected manifest still excludes local guides'
        Assert ($record.source.fingerprintSha256 -match '^[a-f0-9]{64}$') 'Source fingerprint persisted'
        Assert (-not $record.content.completeMetadata) 'Incomplete catalog not misrepresented'
        Assert (Test-Path (Join-Path $built.PrivateBuildDirectory 'private\symbols\ESAIF.TutorialApp.pdb')) 'Private symbols retained outside release'
        Assert (@(Get-ChildItem (Join-Path $built.PrivateBuildDirectory 'payload') -Recurse -Filter '*.pdb').Count -eq 0) 'PDB removed from shipped payload'
        Assert (Test-Path (Join-Path $built.PrivateBuildDirectory 'payload\Licenses\NuGet\synthetic-notice\1.0.0\LICENSE.txt')) 'Available NuGet text included'
        Assert (Test-Path (Join-Path $built.PrivateBuildDirectory 'payload\Licenses\font-inventory.json')) 'Font inventory is included without claiming a license audit'
        Assert (Test-Path (Join-Path $built.PrivateBuildDirectory 'payload\Licenses\Fonts\Apache-2.0.txt')) 'OpenSans upstream license text is included'
        $settings = Get-Content (Join-Path $built.PrivateBuildDirectory 'payload\previewsettings.json') -Raw | ConvertFrom-Json
        Assert (@($settings.PSObject.Properties).Count -eq 1) 'Public configuration contains only API URL'
        Assert ($settings.PreviewApiBaseUri -eq 'https://preview.example.invalid/') 'Client can read generated endpoint setting'
        Assert ($record.artifacts[0].localPath -eq (Join-Path $built.ReleaseDirectory $record.artifacts[0].name)) 'Metadata records actual local artifact path'
        $installerPath = Join-Path $built.ReleaseDirectory $record.artifacts[0].name
        Assert ($record.signing.authenticodeStatus -eq [string](Get-AuthenticodeSignature $installerPath).Status) 'Metadata records actual signature observation (fixture is not a PE)'
        Assert ((Get-FileHash $installerPath -Algorithm SHA256).Hash -ieq $record.artifacts[0].sha256) 'Manifest matches finalized installer hash'
        Assert-Throws { & $publish @packageArgs } 'Existing version cannot be overwritten'
        if ($InnoCompiler) {
            $packageArgs.InnoCompiler = $InnoCompiler
            $packageArgs.OutputRoot = Join-Path $work 'artifacts\compiled-fixture'
            try { $compiled = & $publish @packageArgs } catch {
                Get-ChildItem $packageArgs.OutputRoot -Filter 'installer.log' -Recurse | ForEach-Object { Get-Content $_.FullName | Write-Host }
                throw
            }
            Assert (Test-Path (Join-Path $compiled.ReleaseDirectory $record.artifacts[0].name)) 'Real Inno compiler accepts installer source (never executed)'
        }
        $packageArgs.InnoCompiler = $fakeCompiler
        foreach ($mode in @('tutorial', 'secret', 'source-path', 'api', 'verifier')) {
            $mode | Set-Content "$fakeProject\fixture-mode.txt"
            $packageArgs.OutputRoot = Join-Path $work "artifacts\reject-$mode"
            Assert-Throws { & $publish @packageArgs } "Reject forbidden $mode payload"
            Assert (-not (Test-Path (Join-Path $packageArgs.OutputRoot 'releases\v0.2.0'))) 'Rejected payload never promoted'
        }
        Remove-Item "$fakeProject\fixture-mode.txt"
        $packageArgs.Remove('ApiBaseUri')
        $packageArgs.LocalPreview = $true
        $packageArgs.OutputRoot = Join-Path $work 'artifacts\local-fixture'
        if ($InnoCompiler) { $packageArgs.InnoCompiler = $InnoCompiler }
        $localBuilt = & $publish @packageArgs
        $localRecord = Get-Content (Join-Path $localBuilt.ReleaseDirectory 'release.json') -Raw | ConvertFrom-Json
        $localPayload = Join-Path $localBuilt.PrivateBuildDirectory 'payload'
        Assert ($localRecord.accessMode -eq 'local-invitation-gate/nonconfidential-guides') 'Local manifest states invitation gate is not confidentiality'
        Assert ($localRecord.content.bundled -and -not $localRecord.content.recordingsVerified) 'Local guides bundled without implying working recordings'
        Assert ($null -eq $localRecord.apiBaseUri) 'Local manifest has no API dependency'
        Assert (-not (Test-Path (Join-Path $localPayload 'previewsettings.json'))) 'Local payload has no misleading server endpoint'
        Assert (Test-Path (Join-Path $localPayload 'Tutorials\esaif-python-sdk-01\guide.md')) 'Local payload includes guides'
        Assert (Test-Path (Join-Path $localPayload 'Tutorials\esaif-python-sdk-01\example.py')) 'Tutorial source example allowed only within local guide tree'
        Assert ((Get-FileHash (Join-Path $localPayload 'previewcode.local.json')).Hash -eq (Get-FileHash "$fakeProject\previewcode.local.json").Hash) 'Local payload includes exact validated verifier'
        Assert ((Get-Content (Join-Path $localBuilt.ReleaseDirectory 'release-notes.md') -Raw) -match 'not confidential') 'Local release notes disclose extraction boundary'
        $packageArgs.InnoCompiler = $fakeCompiler
        foreach ($mode in @('secret', 'source-path', 'api', 'nested-verifier', 'tampered-verifier', 'media', 'missing-guide')) {
            $mode | Set-Content "$fakeProject\fixture-mode.txt"
            $packageArgs.OutputRoot = Join-Path $work "artifacts\local-reject-$mode"
            Assert-Throws { & $publish @packageArgs } "Local mode still rejects $mode payload"
            Assert (-not (Test-Path (Join-Path $packageArgs.OutputRoot 'releases\v0.2.0'))) 'Rejected local payload never promoted'
        }
    }
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force
}
"PASS: $checks checks in $([math]::Round($watch.Elapsed.TotalSeconds, 2))s"
