$script:CostOptimizerCommandsRoot = $PSScriptRoot

function STOP-COST-OPTIMIZE-TENANT {
    param([Parameter(Mandatory)][string]$ConfigurationPath, [switch]$Preview, [switch]$NoWait)
    & "$script:CostOptimizerCommandsRoot\Invoke-TenantCostOptimizer.ps1" STOP -ConfigurationPath $ConfigurationPath -Preview:$Preview -NoWait:$NoWait
}

function START-COST-OPTIMIZE-TENANT {
    param([Parameter(Mandatory)][string]$ConfigurationPath, [switch]$Preview, [switch]$NoWait)
    & "$script:CostOptimizerCommandsRoot\Invoke-TenantCostOptimizer.ps1" START -ConfigurationPath $ConfigurationPath -Preview:$Preview -NoWait:$NoWait
}

function STATUS-COST-OPTIMIZE-TENANT {
    param([Parameter(Mandatory)][string]$ConfigurationPath)
    & "$script:CostOptimizerCommandsRoot\Invoke-TenantCostOptimizer.ps1" STATUS -ConfigurationPath $ConfigurationPath
}
