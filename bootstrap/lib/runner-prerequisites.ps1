[CmdletBinding()]
param(
    [switch] $InstallMissing,
    [switch] $RequirePython3,
    [switch] $RequireAzModules,
    [switch] $Scoped
)

$ErrorActionPreference = 'Stop'

function Get-AifRunnerToolSpecs {
    $gitRoot = Join-Path $env:ProgramFiles 'Git'
    @(
        @{ Name = 'git'; Minimum = '2.30'; Arguments = @('--version'); Paths = @((Join-Path $gitRoot 'cmd\git.exe')) }
        @{ Name = 'bash'; Minimum = '4.0'; Arguments = @('--version'); Paths = @((Join-Path $gitRoot 'bin\bash.exe')); Exact = $true }
        @{ Name = 'python'; Minimum = '3.10'; Arguments = @('--version'); Paths = @((Join-Path $env:ProgramFiles 'AIFactory\Python312\python.exe'), 'C:\Python312\python.exe', 'C:\Miniconda\python.exe') }
        @{ Name = 'az'; Minimum = '2.50'; Arguments = @('version', '--output', 'json'); VersionProperty = 'azure-cli'; Paths = @((Join-Path $env:ProgramFiles 'Microsoft SDKs\Azure\CLI2\wbin\az.cmd')) }
        @{ Name = 'pwsh'; Minimum = '7.0'; Arguments = @('--version'); Paths = @((Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe')) }
        @{ Name = 'gh'; Minimum = '2.0'; Arguments = @('--version'); Paths = @((Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe')) }
        # Compile-time imports/functions need the 0.31 generation; 0.44.1 is the CI install pin, not a minimum.
        @{ Name = 'bicep'; Minimum = '0.31.92'; Arguments = @('--version'); Paths = @((Join-Path $env:ProgramFiles 'AIFactory\bin\bicep.exe')) }
        @{ Name = 'jq'; Minimum = '1.6'; Arguments = @('--version'); Paths = @((Join-Path $env:ProgramFiles 'AIFactory\bin\jq.exe')) }
    )
}

function Test-AifRunnerTool {
    param([hashtable] $Spec)
    $path = $null
    if ($Spec.Name -eq 'python' -and (Test-Path -LiteralPath $Spec.Paths[0] -PathType Leaf)) {
        $path = $Spec.Paths[0]
    }
    if (-not $path -and -not $Spec.Exact) {
        $command = Get-Command $Spec.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $path = $command.Source }
    }
    # Never select the Windows System32 WSL bash shim.
    if (-not $path) {
        $path = $Spec.Paths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }
    if (-not $path) {
        return [pscustomobject]@{ Name = $Spec.Name; Status = 'missing'; Path = ''; Version = ''; Minimum = $Spec.Minimum; Reason = 'Executable not found.' }
    }
    $version = ''
    $valid = $false
    $reason = ''
    try {
        $text = (& $path @($Spec.Arguments) 2>&1 | Out-String)
        $code = $LASTEXITCODE
        if ($code -eq 0 -and $Spec.VersionProperty) {
            $text = ($text | ConvertFrom-Json).PSObject.Properties[$Spec.VersionProperty].Value
        }
        if ($code -ne 0) {
            $reason = "Version command exited with code $code."
        } elseif ($text -match '(?<!\d)(\d+\.\d+(?:\.\d+)?)') {
            $version = $Matches[1]
            $valid = [version]$version -ge [version]$Spec.Minimum
            if (-not $valid) { $reason = "Detected $version; requires >= $($Spec.Minimum)." }
        } else {
            $reason = 'Version command did not return a recognizable version.'
        }
    } catch [System.Management.Automation.ApplicationFailedException] {
        $reason = "Executable could not be started: $($_.Exception.Message)"
    } catch [System.ComponentModel.Win32Exception] {
        $reason = "Windows could not execute the version command: $($_.Exception.Message)"
    } catch [System.UnauthorizedAccessException] {
        $reason = "Executable access denied: $($_.Exception.Message)"
    } catch [System.Management.Automation.RemoteException] {
        $reason = "Version command reported an error: $($_.Exception.Message)"
    } catch [System.Management.Automation.CommandNotFoundException] {
        $reason = "Version executable disappeared: $($_.Exception.Message)"
    } catch [System.ArgumentException] {
        $reason = "Version output could not be parsed: $($_.Exception.Message)"
    }
    [pscustomobject]@{
        Name = $Spec.Name; Status = $(if ($valid) { 'ready' } else { 'invalid' })
        Path = $path; Version = $version; Minimum = $Spec.Minimum; Reason = $reason
    }
}

function Get-AifOfficialReleaseAsset {
    param([string] $Repository, [string] $Pattern, [string] $Tag = 'latest')
    $endpoint = if ($Tag -eq 'latest') { 'latest' } else { "tags/$Tag" }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/$endpoint" `
        -Headers @{ Accept = 'application/vnd.github+json'; 'User-Agent' = 'AI-Factory-bootstrap' }
    if ($release.draft -or $release.prerelease) { throw "Refusing non-stable release for $Repository." }
    $assets = @($release.assets | Where-Object { $_.name -like $Pattern })
    if ($assets.Count -ne 1) { throw "Expected one official $Repository release asset matching $Pattern." }
    $asset = $assets[0]
    if ($asset.browser_download_url -notlike "https://github.com/$Repository/releases/download/*") {
        throw "Unexpected release download host/path for $Repository."
    }
    [pscustomobject]@{
        Url = $asset.browser_download_url; Digest = $asset.digest
        Version = (($release.tag_name -replace '^(v|azure-cli-)', '') -replace '\.windows\.1$', '' -replace '\.windows\.', '.'); Name = $asset.name
    }
}

function Save-AifVerifiedDownload {
    param([string] $Url, [string] $Destination, [string] $Digest, [string] $Publisher)
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    $digestVerified = $false
    if ($Digest -match '^sha256:([a-fA-F0-9]{64})$') {
        if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ine $Matches[1]) {
            throw "SHA256 verification failed for $Destination."
        }
        $digestVerified = $true
    } elseif (-not $Publisher) {
        throw "Official SHA256 metadata is unavailable for $Url; refusing unverified installation."
    }
    # Some official release MSIs are digest-published without Authenticode. Either trust chain suffices.
    if ($Publisher -and -not $digestVerified) {
        $signature = Get-AuthenticodeSignature -LiteralPath $Destination
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch $Publisher) {
            throw "Official publisher signature verification failed for $Destination."
        }
    }
}

function Install-AifMissingTool {
    param([string] $Name)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $bin = Join-Path $env:ProgramFiles 'AIFactory\bin'
    $downloadRoot = Join-Path $env:ProgramFiles 'AIFactory\downloads'
    New-Item -ItemType Directory -Path $bin, $downloadRoot -Force | Out-Null
    $asset = $null
    $publisher = ''
    switch ($Name) {
        'git' {
            $asset = Get-AifOfficialReleaseAsset 'git-for-windows/git' 'Git-*-64-bit.exe'
            $publisher = 'Open Source Developer, Johannes Schindelin'
        }
        'python' {
            $asset = [pscustomobject]@{
                Url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
                Digest = ''; Version = '3.12.10'; Name = 'python-3.12.10-amd64.exe'
            }
            $publisher = 'Python Software Foundation'
        }
        'az' {
            $release = Invoke-RestMethod 'https://api.github.com/repos/Azure/azure-cli/releases/latest'
            if ($release.tag_name -notmatch '^azure-cli-(\d+\.\d+\.\d+)$' -or $release.prerelease -or $release.draft) {
                throw 'Could not resolve official Azure CLI version metadata.'
            }
            $asset = [pscustomobject]@{
                Url = "https://azcliprod.blob.core.windows.net/msi/azure-cli-$($Matches[1])-x64.msi"
                Digest = ''; Version = $Matches[1]; Name = 'azure-cli.msi'
            }
            $publisher = 'Microsoft Corporation'
        }
        'pwsh' {
            $asset = Get-AifOfficialReleaseAsset 'PowerShell/PowerShell' 'PowerShell-*-win-x64.msi'
            $publisher = 'Microsoft Corporation'
        }
        'gh' {
            $asset = Get-AifOfficialReleaseAsset 'cli/cli' 'gh_*_windows_amd64.msi'
            $publisher = 'GitHub|Microsoft Corporation'
        }
        'jq' { $asset = Get-AifOfficialReleaseAsset 'jqlang/jq' 'jq-windows-amd64.exe' }
        'bicep' { $asset = Get-AifOfficialReleaseAsset 'Azure/bicep' 'bicep-win-x64.exe' 'v0.44.1' }
        default { throw "No installer for $Name." }
    }
    # Use the same official verified installer even when a Chocolatey mirror lags the release.
    $file = Join-Path $downloadRoot $asset.Name
    if (Test-Path -LiteralPath $file) { throw "Download staging file already exists: $file. Inspect it before retrying." }
    try {
        Save-AifVerifiedDownload $asset.Url $file $asset.Digest $publisher
        if ($Name -in @('bicep', 'jq')) {
            $destination = Join-Path $bin "$Name.exe"
            if (Test-Path -LiteralPath $destination) { throw "Refusing to replace existing $destination." }
            Move-Item -LiteralPath $file -Destination $destination
        } else {
            $executable = $file
            $arguments = @()
            if ($file.EndsWith('.msi')) {
                $executable = 'msiexec.exe'
                $arguments = @('/i', "`"$file`"", '/qn', '/norestart')
            } elseif ($Name -eq 'python') {
                $target = Join-Path $env:ProgramFiles 'AIFactory\Python312'
                $arguments = @('/quiet', '/norestart', 'InstallAllUsers=1', 'PrependPath=0', 'Include_test=0', "TargetDir=`"$target`"")
            } else {
                $arguments = @('/VERYSILENT', '/NORESTART', '/SP-')
            }
            $process = Start-Process -FilePath $executable -ArgumentList $arguments -Wait -PassThru
            if ($process.ExitCode -in @(1641, 3010)) { throw "$Name requires an explicitly scheduled reboot before registration." }
            if ($process.ExitCode -ne 0) { throw "$Name installation failed with exit code $($process.ExitCode)." }
        }
    } finally {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    }
}

function Set-AifRunnerPrerequisiteMarker {
    $directory = Join-Path $env:ProgramFiles 'AIFactory'
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    @{ ChangedUtc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $directory 'prerequisites-changed.json') -Encoding UTF8
}

function Set-AifRunnerMachinePath {
    param([string[]] $ToolPaths)
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $gitBin = Join-Path $env:ProgramFiles 'Git\bin'
    $gitCmd = Join-Path $env:ProgramFiles 'Git\cmd'
    $bin = Join-Path $env:ProgramFiles 'AIFactory\bin'
    $preferred = @($gitBin, $gitCmd, $bin) + @($ToolPaths | ForEach-Object { Split-Path -Parent $_ })
    $pathParts = @($machinePath -split ';' | Where-Object { $_ -and $_ -notin $preferred })
    $updated = (@($preferred | Select-Object -Unique) + $pathParts) -join ';'
    $changed = $machinePath -cne $updated -or
        [Environment]::GetEnvironmentVariable('AZURE_BICEP_USE_BINARY_FROM_PATH', 'Machine') -ne 'true'
    if ($changed) { Set-AifRunnerPrerequisiteMarker }
    if ($changed) { [Environment]::SetEnvironmentVariable('Path', $updated, 'Machine') }
    $env:Path = $updated + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([Environment]::GetEnvironmentVariable('AZURE_BICEP_USE_BINARY_FROM_PATH', 'Machine') -ne 'true') {
        [Environment]::SetEnvironmentVariable('AZURE_BICEP_USE_BINARY_FROM_PATH', 'true', 'Machine')
        $changed = $true
    }
    $env:AZURE_BICEP_USE_BINARY_FROM_PATH = 'true'
    $changed
}

function Test-AifRunnerElevation {
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-AifRunnerPrerequisites {
    [CmdletBinding()]
    param([switch] $InstallMissing, [switch] $RequirePython3, [switch] $RequireAzModules, [switch] $Scoped)
    if ($env:OS -ne 'Windows_NT') { throw 'Use runner-prerequisites.sh on Ubuntu 22.04/24.04.' }
    if ($Scoped) { throw 'Scoped enrollment requires Linux; Windows prerequisites do not establish scoped readiness.' }
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    $specs = @(Get-AifRunnerToolSpecs)
    if ($RequirePython3) {
        $specs += @{ Name = 'python3'; Minimum = '3.10'; Arguments = @('--version'); Paths = @((Join-Path $env:ProgramFiles 'AIFactory\bin\python3.cmd')) }
    }
    $tools = @($specs | ForEach-Object { Test-AifRunnerTool $_ })
    $invalid = @($tools | Where-Object Status -eq 'invalid')
    if ($InstallMissing -and $invalid.Count -eq 1 -and $invalid[0].Name -eq 'python' -and
        $invalid[0].Version -and [version]$invalid[0].Version -lt [version]'3.10') {
        $privatePython = Join-Path $env:ProgramFiles 'AIFactory\Python312\python.exe'
        if (Test-Path -LiteralPath $privatePython) { throw 'The dedicated runner Python exists but is invalid; repair it explicitly.' }
        if (-not (Test-AifRunnerElevation)) { throw '-InstallMissing requires elevation.' }
        Set-AifRunnerPrerequisiteMarker
        Install-AifMissingTool 'python'
        $tools = @($specs | ForEach-Object { Test-AifRunnerTool $_ })
        $invalid = @($tools | Where-Object Status -eq 'invalid')
    }
    if ($invalid) {
        throw "Existing tool version/execution is invalid; no upgrades or replacements are automatic: $($invalid | ConvertTo-Json -Compress)."
    }
    $missing = @($tools | Where-Object Status -eq 'missing')
    if ($missing -and -not $InstallMissing) {
        throw "Missing runner prerequisites (check mode made no changes): $($missing.Name -join ', '). Re-run with -InstallMissing after review."
    }
    $changed = $false
    if ($InstallMissing) {
        if (-not (Test-AifRunnerElevation)) { throw '-InstallMissing requires elevation.' }
        if ($missing.Count) { Set-AifRunnerPrerequisiteMarker }
        foreach ($tool in $missing) {
            if ($tool.Name -eq 'python3') { continue }
            if ($tool.Name -eq 'bash') {
                if (($tools | Where-Object Name -eq 'git').Status -ne 'missing') {
                    throw 'Git exists but its Git Bash component is missing; repair that installation explicitly.'
                }
                continue
            }
            Install-AifMissingTool $tool.Name
        }
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + $env:Path
        $tools = @($specs | ForEach-Object { Test-AifRunnerTool $_ })
        if ($RequirePython3 -and ($tools | Where-Object Name -eq 'python3').Status -eq 'missing') {
            $python = $tools | Where-Object Name -eq 'python'
            if ($python.Status -ne 'ready') { throw 'Cannot create python3 forwarding scripts without a valid Python >=3.10.' }
            $bin = Join-Path $env:ProgramFiles 'AIFactory\bin'
            New-Item -ItemType Directory -Path $bin -Force | Out-Null
            $cmd = Join-Path $bin 'python3.cmd'
            $bash = Join-Path $bin 'python3'
            if ((Test-Path -LiteralPath $cmd) -or (Test-Path -LiteralPath $bash)) { throw 'Refusing to overwrite existing python3 forwarding scripts.' }
            # Only the requested python3 entry point is forwarded; python and pip are never shadowed.
            [IO.File]::WriteAllText($cmd, "@echo off`r`n`"$($python.Path)`" %*`r`nexit /b %errorlevel%`r`n", [Text.Encoding]::ASCII)
            [IO.File]::WriteAllText($bash, "#!/usr/bin/env bash`nexec '$($python.Path.Replace('\', '/'))' `"`$@`"`n", [Text.Encoding]::ASCII)
        }
        $tools = @($specs | ForEach-Object { Test-AifRunnerTool $_ })
    }
    $tools = @($specs | ForEach-Object { Test-AifRunnerTool $_ })
    $failed = @($tools | Where-Object Status -ne 'ready')
    if ($failed) { throw "Prerequisites failed post-install verification: $($failed | ConvertTo-Json -Compress)." }
    if ($RequireAzModules) {
        $moduleScript = @'
param([bool] $InstallMissing)
$ErrorActionPreference = 'Stop'
foreach ($spec in @(@{Name='Az.Accounts'; Minimum=[version]'2.12'}, @{Name='Az.Network'; Minimum=[version]'5.0'})) {
    $module = Get-Module -ListAvailable -Name $spec.Name | Sort-Object Version -Descending | Select-Object -First 1
    if ($module -and $module.Version -lt $spec.Minimum) {
        throw "Existing PowerShell module $($spec.Name) is too old; upgrade it explicitly."
    }
    if (-not $module) {
        if (-not $InstallMissing) { throw "Missing PowerShell module $($spec.Name) (check mode)." }
        $directory = Join-Path $env:ProgramFiles 'AIFactory'
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        @{ ChangedUtc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $directory 'prerequisites-changed.json') -Encoding UTF8
        $version = (Find-Module -Name $spec.Name -Repository PSGallery).Version
        Install-Module -Name $spec.Name -RequiredVersion $version -Repository PSGallery -Scope AllUsers -Force -AcceptLicense
        if (-not (Get-Module -ListAvailable -Name $spec.Name | Where-Object Version -GE $spec.Minimum)) {
            throw "Module $($spec.Name) failed post-install verification."
        }
    }
}
'@
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(
            "& { $moduleScript } -InstallMissing `$$($InstallMissing.IsPresent.ToString().ToLowerInvariant())"))
        $pwsh = ($tools | Where-Object Name -eq 'pwsh').Path
        & $pwsh -NoProfile -NonInteractive -EncodedCommand $encoded
        if ($LASTEXITCODE -ne 0) { throw "Azure PowerShell module verification failed with exit code $LASTEXITCODE." }
    }
    if ($InstallMissing) {
        $changed = Set-AifRunnerMachinePath @($tools | ForEach-Object Path)
    }
    [pscustomobject]@{ Status = 'ready'; ScopedReady = $false; PathChanged = $changed; Tools = $tools }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-AifRunnerPrerequisites -InstallMissing:$InstallMissing -RequirePython3:$RequirePython3 `
        -RequireAzModules:$RequireAzModules -Scoped:$Scoped | ConvertTo-Json -Depth 5
}
