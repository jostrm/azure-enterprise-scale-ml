# Script to update namingConvention module calls in all bicep files
$bicepPath = "c:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\environment_setup\aifactory\bicep\esml-genai-1"
$filesToUpdate = @("04-databases.bicep", "05-compute-services.bicep", "06-ai-platform.bicep", "07-ml-data-platform.bicep", "08-rbac-security.bicep", "09-ai-foundry-2025.bicep")

foreach ($file in $filesToUpdate) {
    $filePath = Join-Path $bicepPath $file
    Write-Host "Checking $file..."
    
    if (Test-Path $filePath) {
        $content = Get-Content $filePath -Raw
        
        # Check if the file has the parameters defined
        $hasAca2 = $content -match "param aca2SubnetId"
        $hasAks2 = $content -match "param aks2SubnetId"
        
        if ($hasAca2 -and $hasAks2) {
            # Check if namingConvention module call exists and needs updating
            if ($content -match "module namingConvention.*?{.*?}") {
                $pattern = "(module namingConvention.*?params:\s*{.*?)(acaSubnetId:\s*acaSubnetId.*?)(.*?})"
                
                if ($content -match $pattern) {
                    $updated = $content -replace $pattern, ('$1$2' + "`n    aca2SubnetId: aca2SubnetId`n    aks2SubnetId: aks2SubnetId" + '$3')
                    
                    if ($updated -ne $content) {
                        Set-Content -Path $filePath -Value $updated -NoNewline
                        Write-Host "Updated $file" -ForegroundColor Green
                    } else {
                        Write-Host "$file already has the parameters" -ForegroundColor Yellow
                    }
                } else {
                    Write-Host "Could not find pattern in $file" -ForegroundColor Red
                }
            } else {
                Write-Host "No namingConvention module found in $file" -ForegroundColor Red
            }
        } else {
            Write-Host "$file is missing parameter definitions (aca2SubnetId: $hasAca2, aks2SubnetId: $hasAks2)" -ForegroundColor Red
        }
    } else {
        Write-Host "File not found: $file" -ForegroundColor Red
    }
}

Write-Host "Update process completed."