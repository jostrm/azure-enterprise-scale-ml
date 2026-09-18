#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $Path,
    [string] $BaseUrl = $(if ($env:AIFACTORY_API_URL) { $env:AIFACTORY_API_URL } else { 'http://127.0.0.1:8765' }),
    [ValidateSet('GET', 'POST')][string] $Method = 'GET',
    [string] $BodyFile,
    [hashtable] $Query = @{},
    [ValidateRange(1, 3600)][int] $TimeoutSeconds = 30,
    [switch] $AllowWrite
)
$ErrorActionPreference = 'Stop'
$client = $null
try {
    $origin = [uri]$BaseUrl
    if (-not $origin.IsAbsoluteUri -or $origin.Scheme -notin @('http', 'https') -or
        $origin.DnsSafeHost -notin @('localhost', '127.0.0.1', '::1') -or
        $origin.UserInfo -or $origin.AbsolutePath -ne '/' -or $origin.Query -or $origin.Fragment) {
        throw 'Use the local API origin, without credentials, path, query or fragment.'
    }
    if ($Path -cnotmatch '^/(health|openapi\.json|api/v1/[A-Za-z0-9_/-]+)$' -or $Path.Contains('//')) {
        throw 'Use a literal API path; pass query values with -Query.'
    }
    if ($Method -ne 'GET' -and -not $AllowWrite) { throw 'POST requires -AllowWrite, including prepare.' }
    if ($Method -eq 'GET' -and $BodyFile) { throw 'GET cannot have a request body.' }
    $builder = [UriBuilder]::new([uri]::new($origin, $Path))
    $builder.Query = (($Query.GetEnumerator() | ForEach-Object {
        [uri]::EscapeDataString([string]$_.Key) + '=' + [uri]::EscapeDataString([string]$_.Value)
    }) -join '&')
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [timespan]::FromSeconds($TimeoutSeconds)
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $builder.Uri)
    $request.Headers.Accept.ParseAdd('application/json')
    if ($Path.StartsWith('/api/v1/')) {
        if (-not $env:AIFACTORY_API_KEY) { throw 'Set AIFACTORY_API_KEY in this process.' }
        $request.Headers.Add('X-API-Key', $env:AIFACTORY_API_KEY)
    }
    if ($BodyFile) {
        $body = Get-Content -LiteralPath $BodyFile -Raw | ConvertFrom-Json -AsHashtable
        if ($body -isnot [System.Collections.IDictionary]) { throw 'Body must be a JSON object.' }
        $json = ConvertTo-Json -InputObject $body -Depth 100 -Compress
        if ($json.Contains('${')) { throw 'Render placeholders before sending.' }
        $request.Content = [System.Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, 'application/json')
    }
    $response = $client.SendAsync($request).GetAwaiter().GetResult()
    $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if ($env:AIFACTORY_API_KEY) { $text = $text.Replace($env:AIFACTORY_API_KEY, '[REDACTED]') }
    if (-not $response.IsSuccessStatusCode) { throw "HTTP $([int]$response.StatusCode): $text" }
    $result = ConvertFrom-Json -InputObject $text -AsHashtable
    ConvertTo-Json -InputObject $result -Depth 100
    if ($result -is [System.Collections.IDictionary]) {
        if ($result.can_execute -eq $false -or $result.blockers.Count -gt 0) { exit 3 }
        if ($result.status -in @('failed', 'interrupted')) { exit 4 }
    }
}
catch {
    $message = $_.Exception.Message
    if ($env:AIFACTORY_API_KEY) { $message = $message.Replace($env:AIFACTORY_API_KEY, '[REDACTED]') }
    [Console]::Error.WriteLine($message)
    exit 2
}
finally {
    if ($client) { $client.Dispose() }
}
