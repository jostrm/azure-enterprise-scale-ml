function Load-EnvFile {
    param(
        [string]$EnvFile = ".env"
    )
    
    if (Test-Path $EnvFile) {
        Get-Content $EnvFile | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
                $name = $matches[1].Trim()
                $value = $matches[2].Trim()
                Set-Item -Path "env:$name" -Value $value
                Write-Host "Loaded: $name"
            }
        }
    } else {
        Write-Warning "Environment file not found: $EnvFile"
    }
}