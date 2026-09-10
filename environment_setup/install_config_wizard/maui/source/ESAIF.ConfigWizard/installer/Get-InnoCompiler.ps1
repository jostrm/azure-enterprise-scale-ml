$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$tools = Join-Path $root "artifacts\installer-tools"
$local = Join-Path $tools "InnoSetup\ISCC.exe"
$candidates = @(
    $local,
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
)
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) { return $candidate }
}
New-Item -ItemType Directory -Path $tools -Force | Out-Null
$download = Join-Path $tools "innosetup-6.4.3.exe"
Invoke-WebRequest "https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe" -OutFile $download
if ((Get-FileHash $download -Algorithm SHA256).Hash -ne "F3C42116542C4CC57263C5BA6C4FEABFC49FE771F2F98A79D2F7628B8762723B") {
    throw "Inno Setup 6.4.3 download checksum mismatch."
}
if ((Get-AuthenticodeSignature $download).Status -ne "Valid") { throw "Inno Setup publisher signature is not valid." }
$process = Start-Process $download -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
    '/CURRENTUSER', '/NOICONS', '/TASKS=', '/TYPE=compact', "/DIR=`"$(Join-Path $tools 'InnoSetup')`"") -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path $local)) { throw "Local Inno Setup compiler installation failed." }
return $local
