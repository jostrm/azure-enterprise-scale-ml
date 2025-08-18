# ============================================================================
# AI Factory Multi-Deployment Orchestrator Script
# ============================================================================
# This PowerShell script orchestrates the sequential deployment of the split Bicep templates
# Run this instead of the monolithic 32-main.bicep for better management and reliability

param(
    [Parameter(Mandatory = $true)]
    [string]$ParameterFile,
    
    [Parameter(Mandatory = $false)]
    [string]$Location = "swedencentral",
    
    [Parameter(Mandatory = $false)]
    [ValidateSet("dev", "test", "prod")]
    [string]$Environment = "dev",
    
    [Parameter(Mandatory = $false)]
    [switch]$WhatIf,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipFoundation,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipCognitiveServices,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipCoreInfrastructure,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipDatabases,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipComputeServices,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipMLPlatform,
    
    [Parameter(Mandatory = $false)]
    [switch]$SkipRBACAndSecurity,
    
    [Parameter(Mandatory = $false)]
    [int]$TimeoutMinutes = 60
)

# ============================================================================
# CONFIGURATION & SETUP
# ============================================================================

$ErrorActionPreference = "Stop"
$deploymentPrefix = "aifactory-split-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$currentPath = $PSScriptRoot

# Deployment sequence and configuration
$deployments = @(
    @{
        Name = "Foundation"
        File = "01-foundation.bicep"
        Skip = $SkipFoundation
        Description = "Core infrastructure and foundational services"
        Dependencies = @()
        EstimatedMinutes = 10
    },
    @{
        Name = "CognitiveServices"
        File = "02-cognitive-services.bicep"
        Skip = $SkipCognitiveServices
        Description = "All AI/ML cognitive services"
        Dependencies = @("Foundation")
        EstimatedMinutes = 15
    },
    @{
        Name = "CoreInfrastructure"
        File = "03-core-infrastructure.bicep"
        Skip = $SkipCoreInfrastructure
        Description = "Storage, networking, and core services"
        Dependencies = @("Foundation")
        EstimatedMinutes = 15
    },
    @{
        Name = "Databases"
        File = "04-databases.bicep"
        Skip = $SkipDatabases
        Description = "All database services"
        Dependencies = @("CoreInfrastructure")
        EstimatedMinutes = 20
    },
    @{
        Name = "ComputeServices"
        File = "05-compute-services.bicep"
        Skip = $SkipComputeServices
        Description = "Web apps, functions, and container apps"
        Dependencies = @("CoreInfrastructure")
        EstimatedMinutes = 15
    },
    @{
        Name = "MLPlatform"
        File = "06-ml-platform.bicep"
        Skip = $SkipMLPlatform
        Description = "Azure ML and AI Foundry Hub"
        Dependencies = @("CognitiveServices", "CoreInfrastructure")
        EstimatedMinutes = 10
    },
    @{
        Name = "RBACAndSecurity"
        File = "07-rbac-security.bicep"
        Skip = $SkipRBACAndSecurity
        Description = "All role-based access control and security"
        Dependencies = @("Foundation", "CognitiveServices", "CoreInfrastructure", "Databases", "ComputeServices", "MLPlatform")
        EstimatedMinutes = 10
    }
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

function Write-DeploymentHeader {
    param([string]$Title, [string]$Description)
    
    Write-Host ""
    Write-Host "=" * 80 -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Yellow
    Write-Host "  $Description" -ForegroundColor Gray
    Write-Host "=" * 80 -ForegroundColor Cyan
    Write-Host ""
}

function Write-DeploymentStatus {
    param([string]$Status, [string]$Message, [string]$Color = "White")
    
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$timestamp] [$Status] $Message" -ForegroundColor $Color
}

function Test-DeploymentFile {
    param([string]$FilePath)
    
    if (-not (Test-Path $FilePath)) {
        throw "Deployment file not found: $FilePath"
    }
    
    # Test Bicep compilation
    Write-DeploymentStatus "VALIDATE" "Compiling Bicep template: $FilePath" "Yellow"
    $buildResult = az bicep build --file $FilePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Bicep compilation failed for $FilePath`: $buildResult"
    }
    Write-DeploymentStatus "VALIDATE" "Bicep compilation successful" "Green"
}

function Start-TemplateDeployment {
    param(
        [string]$DeploymentName,
        [string]$TemplateFile,
        [string]$ParameterFile,
        [string]$Location,
        [bool]$WhatIfMode,
        [int]$TimeoutMinutes
    )
    
    $deploymentId = "$deploymentPrefix-$DeploymentName"
    
    if ($WhatIfMode) {
        Write-DeploymentStatus "WHATIF" "Running what-if analysis..." "Cyan"
        $result = az deployment sub what-if `
            --name $deploymentId `
            --location $Location `
            --template-file $TemplateFile `
            --parameters "@$ParameterFile" `
            2>&1
    } else {
        Write-DeploymentStatus "DEPLOY" "Starting deployment..." "Green"
        $result = az deployment sub create `
            --name $deploymentId `
            --location $Location `
            --template-file $TemplateFile `
            --parameters "@$ParameterFile" `
            --timeout $($TimeoutMinutes * 60) `
            2>&1
    }
    
    if ($LASTEXITCODE -ne 0) {
        throw "Deployment failed: $result"
    }
    
    return $result
}

function Get-DeploymentOutputs {
    param([string]$DeploymentName)
    
    try {
        $deploymentId = "$deploymentPrefix-$DeploymentName"
        $outputs = az deployment sub show --name $deploymentId --query "properties.outputs" --output json | ConvertFrom-Json
        return $outputs
    } catch {
        Write-DeploymentStatus "WARNING" "Could not retrieve outputs from $DeploymentName" "Yellow"
        return $null
    }
}

# ============================================================================
# MAIN DEPLOYMENT LOGIC
# ============================================================================

try {
    Write-DeploymentHeader "AI Factory Multi-Deployment Orchestrator" "Deploying split Bicep templates in sequence"
    
    # Validate prerequisites
    Write-DeploymentStatus "INIT" "Validating prerequisites..." "Cyan"
    
    if (-not (Test-Path $ParameterFile)) {
        throw "Parameter file not found: $ParameterFile"
    }
    
    # Check Azure CLI
    $azVersion = az version --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI not found or not logged in. Please run 'az login' first."
    }
    
    Write-DeploymentStatus "INIT" "Prerequisites validated successfully" "Green"
    
    # Track deployment results
    $deploymentResults = @{}
    $totalEstimatedTime = ($deployments | Where-Object { -not $_.Skip } | Measure-Object -Property EstimatedMinutes -Sum).Sum
    $startTime = Get-Date
    
    Write-DeploymentStatus "PLAN" "Estimated total deployment time: $totalEstimatedTime minutes" "Cyan"
    
    if ($WhatIf) {
        Write-DeploymentStatus "WHATIF" "Running in WHAT-IF mode - no resources will be deployed" "Magenta"
    }
    
    # Execute deployments in sequence
    foreach ($deployment in $deployments) {
        if ($deployment.Skip) {
            Write-DeploymentStatus "SKIP" "Skipping $($deployment.Name)" "Gray"
            continue
        }
        
        $deploymentFile = Join-Path $currentPath $deployment.File
        
        # Check if file exists (some may not be created yet)
        if (-not (Test-Path $deploymentFile)) {
            Write-DeploymentStatus "SKIP" "$($deployment.Name) - File not found: $($deployment.File)" "Yellow"
            continue
        }
        
        try {
            Write-DeploymentHeader $deployment.Name $deployment.Description
            
            # Validate dependencies
            foreach ($dependency in $deployment.Dependencies) {
                if (-not $deploymentResults.ContainsKey($dependency)) {
                    throw "Dependency not met: $dependency must be deployed before $($deployment.Name)"
                }
            }
            
            # Test deployment file
            Test-DeploymentFile $deploymentFile
            
            # Execute deployment
            $deploymentStart = Get-Date
            $result = Start-TemplateDeployment `
                -DeploymentName $deployment.Name `
                -TemplateFile $deploymentFile `
                -ParameterFile $ParameterFile `
                -Location $Location `
                -WhatIfMode $WhatIf `
                -TimeoutMinutes $TimeoutMinutes
            
            $deploymentEnd = Get-Date
            $deploymentDuration = ($deploymentEnd - $deploymentStart).TotalMinutes
            
            # Track results
            $deploymentResults[$deployment.Name] = @{
                Status = "Success"
                Duration = $deploymentDuration
                StartTime = $deploymentStart
                EndTime = $deploymentEnd
            }
            
            if (-not $WhatIf) {
                $outputs = Get-DeploymentOutputs $deployment.Name
                $deploymentResults[$deployment.Name].Outputs = $outputs
            }
            
            Write-DeploymentStatus "SUCCESS" "$($deployment.Name) completed in $([math]::Round($deploymentDuration, 1)) minutes" "Green"
            
        } catch {
            $deploymentResults[$deployment.Name] = @{
                Status = "Failed"
                Error = $_.Exception.Message
                StartTime = $deploymentStart
                EndTime = Get-Date
            }
            
            Write-DeploymentStatus "ERROR" "$($deployment.Name) failed: $($_.Exception.Message)" "Red"
            
            # Ask if user wants to continue or abort
            $continue = Read-Host "Do you want to continue with remaining deployments? (y/N)"
            if ($continue -notmatch "^[Yy]") {
                throw "Deployment aborted by user"
            }
        }
    }
    
    # ============================================================================
    # DEPLOYMENT SUMMARY
    # ============================================================================
    
    $endTime = Get-Date
    $totalDuration = ($endTime - $startTime).TotalMinutes
    
    Write-DeploymentHeader "Deployment Summary" "Overview of all deployment results"
    
    Write-Host "Total deployment time: $([math]::Round($totalDuration, 1)) minutes" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($deployment in $deployments) {
        if ($deployment.Skip -or -not $deploymentResults.ContainsKey($deployment.Name)) {
            continue
        }
        
        $result = $deploymentResults[$deployment.Name]
        $status = $result.Status
        $color = if ($status -eq "Success") { "Green" } else { "Red" }
        
        Write-Host "  $($deployment.Name.PadRight(20)) : $status" -ForegroundColor $color
        
        if ($result.Duration) {
            Write-Host "    Duration: $([math]::Round($result.Duration, 1)) minutes" -ForegroundColor Gray
        }
        
        if ($result.Error) {
            Write-Host "    Error: $($result.Error)" -ForegroundColor Red
        }
    }
    
    # Check overall success
    $failedDeployments = $deploymentResults.Values | Where-Object { $_.Status -eq "Failed" }
    if ($failedDeployments.Count -eq 0) {
        Write-Host ""
        Write-DeploymentStatus "COMPLETE" "All deployments completed successfully!" "Green"
        exit 0
    } else {
        Write-Host ""
        Write-DeploymentStatus "PARTIAL" "$($failedDeployments.Count) deployment(s) failed" "Yellow"
        exit 1
    }
    
} catch {
    Write-DeploymentStatus "FATAL" "Fatal error: $($_.Exception.Message)" "Red"
    Write-Host "Stack trace:" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 2
}

# ============================================================================
# USAGE EXAMPLES
# ============================================================================

<#
.SYNOPSIS
    Orchestrates the deployment of split AI Factory Bicep templates

.DESCRIPTION
    This script replaces the monolithic 32-main.bicep deployment with a series of 
    smaller, more manageable deployments that can be executed independently or 
    in sequence with proper dependency management.

.PARAMETER ParameterFile
    Path to the JSON parameter file (same format as used with 32-main.bicep)

.PARAMETER Location
    Azure region for deployment (default: swedencentral)

.PARAMETER Environment
    Environment type: dev, test, or prod (default: dev)

.PARAMETER WhatIf
    Run in what-if mode to preview changes without deploying

.PARAMETER TimeoutMinutes
    Timeout for each individual deployment in minutes (default: 60)

.PARAMETER Skip*
    Skip specific deployment layers for testing or partial deployments

.EXAMPLE
    # Full deployment
    .\Deploy-AIFactory-Split.ps1 -ParameterFile "parameters.json" -Environment dev

.EXAMPLE
    # What-if analysis
    .\Deploy-AIFactory-Split.ps1 -ParameterFile "parameters.json" -WhatIf

.EXAMPLE
    # Skip certain layers
    .\Deploy-AIFactory-Split.ps1 -ParameterFile "parameters.json" -SkipDatabases -SkipComputeServices

.EXAMPLE
    # Foundation only
    .\Deploy-AIFactory-Split.ps1 -ParameterFile "parameters.json" -SkipCognitiveServices -SkipCoreInfrastructure -SkipDatabases -SkipComputeServices -SkipMLPlatform -SkipRBACAndSecurity
#>
