<#
.SYNOPSIS
    Shared AI Factory helpers reused by every report runbook: project naming/RG resolution
    (GitHub .env / ADO variables.yaml / config), auth, resource discovery, blob output.
#>

function Get-EnvSettings {
    param([string]$Path)
    $h = @{}
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k,$v = $line -split '=',2
        $h[$k.Trim()] = ($v -replace '\s+#.*$','').Trim().Trim('"').Trim("'")
    }
    return $h
}

function Get-AdoSettings {
    param([string]$Path)
    $h = @{}
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match '^\s*#' -or $line -match '^\s*variables\s*:') { continue }
        if ($line -match '^\s{2,}([A-Za-z0-9_]+)\s*:\s*(.+)$') {
            $h[$matches[1].Trim()] = ($matches[2] -replace '\s+#.*$','').Trim().Trim('"').Trim("'")
        }
    }
    return $h
}

# Build the common naming hashtable from a github/ado settings file, falling back to project-config.json.
function Resolve-ProjectNaming {
    param(
        [ValidateSet('github','ado','config')] [string]$Source = 'config',
        [string]$SettingsPath,
        [string]$ConfigPath
    )
    if ($Source -eq 'config') {
        if (-not (Test-Path $ConfigPath)) { throw "project-config.json not found: $ConfigPath" }
        return (Get-Content -Raw $ConfigPath | ConvertFrom-Json).naming
    }
    if (-not (Test-Path $SettingsPath)) { throw "Settings file for source '$Source' not found: $SettingsPath" }
    Write-Output "Reading naming from '$Source': $SettingsPath"
    if ($Source -eq 'github') {
        $s = Get-EnvSettings $SettingsPath
        return @{ aifactoryPrefix=$s.AIFACTORY_PREFIX; aifactorySuffix=$s.AIFACTORY_SUFFIX; projectPrefix=$s.PROJECT_PREFIX;
                  projectSuffix=$s.PROJECT_SUFFIX; projectNumber=$s.PROJECT_NUMBER; locationShort=$s.AIFACTORY_LOCATION_SHORT;
                  env='dev'; vnetResourceGroupBase=$s.VNET_RESOURCE_GROUP_BASE }
    }
    $s = Get-AdoSettings $SettingsPath
    return @{ aifactoryPrefix=$s.admin_aifactoryPrefixRG; aifactorySuffix=$s.admin_aifactorySuffixRG; projectPrefix=$s.projectPrefix;
              projectSuffix=$s.projectSuffix; projectNumber=$s.project_number_000; locationShort=$s.admin_locationSuffix;
              env=($s.ContainsKey('dev_test_prod') -and $s.dev_test_prod ? $s.dev_test_prod : 'dev'); vnetResourceGroupBase=$s.vnetResourceGroupBase }
}

# Project RG: {prefix}{projectPrefix}project{NNN}-{loc}-{env}{aifSuffix}{prjSuffix}
# Common RG : {prefix}{vnetResourceGroupBase}-{loc}-{env}{aifSuffix}
function Get-AifResourceGroups {
    param([hashtable]$n)
    [pscustomobject]@{
        ProjectRg = "$($n.aifactoryPrefix)$($n.projectPrefix)project$($n.projectNumber)-$($n.locationShort)-$($n.env)$($n.aifactorySuffix)$($n.projectSuffix)"
        CommonRg  = "$($n.aifactoryPrefix)$($n.vnetResourceGroupBase)-$($n.locationShort)-$($n.env)$($n.aifactorySuffix)"
    }
}

function Connect-Aif {
    param([string]$SubscriptionId,[string]$UamiClientId,[switch]$UseCurrentLogin)
    if ($UseCurrentLogin)      { Write-Output 'Using existing Az PowerShell login.' }
    elseif ($UamiClientId)     { Connect-AzAccount -Identity -AccountId $UamiClientId | Out-Null }
    else                       { Connect-AzAccount -Identity | Out-Null }
    if ($SubscriptionId) { Select-AzSubscription -SubscriptionId $SubscriptionId | Out-Null }
    return (Get-AzContext).Subscription.Id
}

function Get-ProjectUami {
    param([string]$ProjectRg)
    Get-AzResource -ResourceGroupName $ProjectRg -ResourceType 'Microsoft.ManagedIdentity/userAssignedIdentities' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'mi-prj*' } | Select-Object -First 1
}

function Get-ProjectLogAnalytics {
    param([string]$CommonRg,[string]$Name)
    if ($Name) { return Get-AzOperationalInsightsWorkspace -ResourceGroupName $CommonRg -Name $Name }
    $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $CommonRg -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'la-cmn-*' } | Select-Object -First 1
    if (-not $law) { $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $CommonRg -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $law) { throw "No Log Analytics workspace found in $CommonRg" }
    return $law
}

function Write-ReportToBlob {
    param([string]$Markdown,[string]$ProjectRg,[string]$StorageAccount,[string]$Container,[string]$Blob)
    $tmp = New-TemporaryFile; $Markdown | Out-File -FilePath $tmp -Encoding utf8
    $ctx = (Get-AzStorageAccount -ResourceGroupName $ProjectRg -Name $StorageAccount).Context
    Set-AzStorageBlobContent -File $tmp -Container $Container -Blob $Blob -Context $ctx -Force | Out-Null
}

# Markdown -> styled HTML (headings, tables, blockquotes, hr, inline **bold**/`code`/*italic*).
# State machine: first row of each pipe-table is the header (th), the |---| separator confirms it,
# following rows are data (td). Consecutive '>' lines merge into one blockquote.
function ConvertTo-ReportHtml {
    param([string]$Markdown,[string]$Title = 'AI Factory Report')

    # Escape HTML then apply inline markdown (order matters: code before bold to protect backticks).
    function Convert-Inline {
        param([string]$Text)
        $t = $Text -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;'
        $t = [regex]::Replace($t, '`([^`]+)`', '<code>$1</code>')
        $t = [regex]::Replace($t, '\*\*([^*]+)\*\*', '<strong>$1</strong>')
        $t = [regex]::Replace($t, '(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)', '<em>$1</em>')
        return $t
    }

    $sb = New-Object System.Text.StringBuilder
    $inTable = $false          # currently inside a pipe-table
    $tableRowSeen = $false     # header row already emitted for the current table
    $quoteBuffer = New-Object System.Collections.Generic.List[string]

    function Flush-Quote {
        if ($quoteBuffer.Count -gt 0) {
            [void]$sb.Append('<blockquote>' + (($quoteBuffer | ForEach-Object { Convert-Inline $_ }) -join '<br>') + '</blockquote>')
            $quoteBuffer.Clear()
        }
    }

    foreach ($line in ($Markdown -split "`r?`n")) {
        $trim = $line.Trim()

        # Blockquote accumulation
        if ($trim -match '^>\s?(.*)$') { $quoteBuffer.Add($matches[1]); continue } else { Flush-Quote }

        # Table separator |---|:|--- -> confirms header, emit nothing
        if ($trim -match '^\|[\s:\-\|]+\|$') { $tableRowSeen = $true; continue }

        # Table row
        if ($trim -match '^\|.*\|$') {
            if (-not $inTable) { [void]$sb.Append('<table>'); $inTable = $true; $tableRowSeen = $false }
            $isHeader = -not $tableRowSeen
            $cells = ($trim.Trim('|') -split '\|').ForEach({ $_.Trim() })
            $tag = if ($isHeader) { 'th' } else { 'td' }
            [void]$sb.Append('<tr>')
            foreach ($c in $cells) { [void]$sb.Append("<$tag>$(Convert-Inline $c)</$tag>") }
            [void]$sb.Append('</tr>')
            $tableRowSeen = $true
            continue
        } elseif ($inTable) { [void]$sb.Append('</table>'); $inTable = $false }

        if     ($trim -eq '')                { continue }
        elseif ($trim -match '^-{3,}$')      { [void]$sb.Append('<hr>') }
        elseif ($trim -match '^###\s+(.*)')  { [void]$sb.Append("<h3>$(Convert-Inline $matches[1])</h3>") }
        elseif ($trim -match '^##\s+(.*)')   { [void]$sb.Append("<h2>$(Convert-Inline $matches[1])</h2>") }
        elseif ($trim -match '^#\s+(.*)')    { [void]$sb.Append("<h1>$(Convert-Inline $matches[1])</h1>") }
        else                                 { [void]$sb.Append("<p>$(Convert-Inline $trim)</p>") }
    }
    Flush-Quote
    if ($inTable) { [void]$sb.Append('</table>') }

    @"
<!doctype html><html><head><meta charset='utf-8'><title>$Title</title>
<style>body{font-family:Segoe UI,Arial;margin:32px;color:#222;line-height:1.45}
h1{border-bottom:2px solid #444;padding-bottom:4px}h2{margin-top:24px}
table{border-collapse:collapse;margin:12px 0;width:100%;font-size:14px}
th,td{border:1px solid #bbb;padding:6px 10px;text-align:left;vertical-align:top}
th{background:#f2f4f7}tr td:nth-child(n+5){text-align:right}
code{background:#f4f4f4;padding:1px 4px;border-radius:3px;font-family:Consolas,monospace;font-size:90%}
blockquote{border-left:4px solid #ccc;margin:10px 0;padding:4px 14px;color:#555;background:#fafafa}
hr{border:0;border-top:1px solid #ddd;margin:20px 0}</style></head><body>$($sb.ToString())</body></html>
"@
}

# Best-effort PDF: HTML always, PDF via headless Edge/Chrome -> PSWritePDF -> else HTML only.
function Export-ReportFiles {
    param([string]$Markdown,[string]$BaseName,[string]$OutDir = $PWD)
    if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
    $OutDir = (Resolve-Path $OutDir).Path
    $md = Join-Path $OutDir "$BaseName.md"; $html = Join-Path $OutDir "$BaseName.html"; $pdf = Join-Path $OutDir "$BaseName.pdf"
    $Markdown | Out-File $md -Encoding utf8
    (ConvertTo-ReportHtml -Markdown $Markdown) | Out-File $html -Encoding utf8
    $browser = @('msedge','chrome') | ForEach-Object { (Get-Command $_ -EA SilentlyContinue).Source } | Where-Object { $_ } | Select-Object -First 1
    if (-not $browser) { foreach ($p in 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','C:\Program Files\Microsoft\Edge\Application\msedge.exe','C:\Program Files\Google\Chrome\Application\chrome.exe') { if (Test-Path $p) { $browser=$p; break } } }
    if ($browser) {
        $uri  = 'file:///' + ((Resolve-Path $html).Path -replace '\\','/')
        $prof = Join-Path $env:TEMP ('aifpdf-' + (Get-Random))
        $eargs = @('--headless=new','--disable-gpu','--no-pdf-header-footer',"--user-data-dir=$prof","--print-to-pdf=$pdf",$uri)
        $proc = Start-Process $browser -ArgumentList $eargs -PassThru -WindowStyle Hidden
        if (-not $proc.WaitForExit(20000)) { try { $proc.Kill() } catch {} }
        Remove-Item $prof -Recurse -Force -EA SilentlyContinue
    }
    if (-not (Test-Path $pdf) -and (Get-Module -ListAvailable PSWritePDF)) {
        Import-Module PSWritePDF; ConvertTo-PDF -InputFile $html -OutputFile $pdf -ErrorAction SilentlyContinue
    }
    [pscustomobject]@{ Md=$md; Html=$html; Pdf=((Test-Path $pdf) ? $pdf : $null) }
}

# Upload the .md/.html/.pdf produced by Export-ReportFiles to a project storage container.
function Write-ReportFilesToBlob {
    param([pscustomobject]$Files,[string]$ProjectRg,[string]$StorageAccount,[string]$Container = 'reports',[string]$Prefix = '')
    $ctx = (Get-AzStorageAccount -ResourceGroupName $ProjectRg -Name $StorageAccount).Context
    foreach ($f in @($Files.Md,$Files.Html,$Files.Pdf)) {
        if ($f -and (Test-Path $f)) {
            Set-AzStorageBlobContent -File $f -Container $Container -Blob ($Prefix + (Split-Path $f -Leaf)) -Context $ctx -Force | Out-Null
        }
    }
}

Export-ModuleMember -Function Get-EnvSettings,Get-AdoSettings,Resolve-ProjectNaming,Get-AifResourceGroups,Connect-Aif,Get-ProjectUami,Get-ProjectLogAnalytics,Write-ReportToBlob,ConvertTo-ReportHtml,Export-ReportFiles,Write-ReportFilesToBlob
