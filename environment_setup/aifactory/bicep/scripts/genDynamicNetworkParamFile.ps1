
param (
    # required
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar1,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar2,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar3,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar4,
    [Parameter(Mandatory = $true, HelpMessage="Where to place the parameters.json file")][string]$filePath,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory environment [dev,test,prod]")][string]$env,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory subscription id for environment [dev,test,prod]")][string]$subscriptionId,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory COMMON RG, suffix ")][string]$aifactorySuffixRGADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory location suffix ")][string]$locationSuffixADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML projectNumber -makes a deployment unique per proj and env")][string]$projectNumber,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory project type:[esml,genai-1]")][string]$projectTypeADO,
    
    # optional
    [Parameter(Mandatory = $false, HelpMessage = "ESML AI Factory COMMON RG, suffix ")][string]$commonRGNamePrefixVar,
    [Parameter(Mandatory = $false, HelpMessage="Use service principal")][switch]$useServicePrincipal=$false,
    [Parameter(Mandatory = $false, HelpMessage="Specifies the object id for service principal")][string]$spObjId,
    [Parameter(Mandatory = $false, HelpMessage="Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar5,
    [Parameter(Mandatory = $false, HelpMessage = "Bring your own subnets, true or false string")][string]$BYO_subnets,
    [Parameter(Mandatory = $false, HelpMessage = "Bring your own subnets. <network_env> dev-, test-, prod- or other env name")][string]$network_env,
    [Parameter(Mandatory = $false, HelpMessage = "Save generated file to Git repository (Azure DevOps or GitHub)")][bool]$saveFileInADOGitRepo = $true
)

function Set-DeployedOnTag {
    [CmdletBinding()]
    param (
        [Parameter(ValueFromPipeline)]
        $InputObject
    )
    process {
        $deployedOn = get-date -format "yyyy/MM/dd HH:mm"
        try {
            $obj = [PSCustomObject]@{
                value = @{Deployed=$deployedOn}
            }
            Add-Member -InputObject $InputObject.parameters -NotePropertyName "tags" -NotePropertyValue $obj -ErrorAction "Stop"
        }
        catch {
            Add-Member -InputObject $InputObject.parameters.tags.value -NotePropertyName "deployedOn" -NotePropertyValue $deployedOn 
        }
        $InputObject
    }
}

function Get-AzureSubnetId {
    param (
        [string]$subscriptionId,
        [string]$resourceGroupName,
        [string]$vnetName,
        [string]$subnetName,
        [string]$projectNumber = "",
        [string]$networkEnv = ""
    )
    
    # Replace placeholders if network environment is specified
    if ($networkEnv -ne "") {
        $vnetName = $vnetName -replace '<network_env>', $networkEnv
        $subnetName = $subnetName -replace '<network_env>', $networkEnv
    }
    if ($projectNumber -ne "") {
        $subnetName = $subnetName -replace '<xxx>', $projectNumber
    }
    
    return "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.Network/virtualNetworks/$vnetName/subnets/$subnetName"
}

function Save-FileToGitRepository {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$CommitMessage = "Update dynamicNetworkParams.json via pipeline"
    )
    
    try {
        # Get current working directory for Git operations
        $currentLocation = Get-Location
        Write-Host "Current location: $currentLocation"
        
        # Check if we're in a Git repository
        $gitStatus = git status --porcelain 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Not in a Git repository or Git is not available. File saved locally only."
            return $false
        }
        
        # Detect Git repository type
        $gitRemoteUrl = git remote get-url origin 2>&1
        $isAzureDevOps = $false
        $isGitHub = $false
        
        if ($gitRemoteUrl -match "dev.azure.com|visualstudio.com") {
            $isAzureDevOps = $true
            Write-Host "Detected Azure DevOps repository"
        } elseif ($gitRemoteUrl -match "github.com") {
            $isGitHub = $true
            Write-Host "Detected GitHub repository"
        } else {
            Write-Host "Detected Git repository (type unknown): $gitRemoteUrl"
        }
        
        # Get relative path for Git operations
        $relativePath = if (Test-Path $FilePath) {
            (Resolve-Path -Path $FilePath -Relative).TrimStart('./')
        } else {
            Write-Warning "File does not exist: $FilePath"
            return $false
        }
        
        # Check if file has changes or is new
        $gitStatusOutput = git status --porcelain $FilePath 2>&1
        $hasChanges = $gitStatusOutput -and ($gitStatusOutput.Length -gt 0)
        
        # If no changes, check if file exists in Git history
        if (-not $hasChanges) {
            $gitLsFiles = git ls-files $FilePath 2>&1
            if (-not $gitLsFiles -or $LASTEXITCODE -ne 0) {
                # File is not tracked, so it's new
                $hasChanges = $true
                Write-Host "File is new and will be added to Git"
            } else {
                Write-Host "No changes detected in file: $relativePath (file content is the same as in repository)"
                return $true
            }
        }
        
        if ($hasChanges) {
            Write-Host "Adding file to Git: $relativePath"
            git add $FilePath
            
            if ($LASTEXITCODE -eq 0) {
                # Check if there's actually something to commit after staging
                $gitDiffCached = git diff --cached --name-only
                if (-not $gitDiffCached) {
                    Write-Host "No changes to commit after staging (file content unchanged)"
                    return $true
                }
                
                Write-Host "Committing changes with message: $CommitMessage"
                git commit -m $CommitMessage
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Pushing changes to remote repository..."
                    
                    # Get current branch
                    $currentBranch = git branch --show-current
                    Write-Host "Current branch: $currentBranch"
                    
                    # Try to push with error handling
                    git push origin $currentBranch 2>&1
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "Successfully pushed changes to Git repository"
                        if ($isAzureDevOps) {
                            Write-Host "File available in Azure DevOps at: $gitRemoteUrl"
                        } elseif ($isGitHub) {
                            Write-Host "File available in GitHub at: $gitRemoteUrl"
                        }
                        return $true
                    } else {
                        Write-Warning "Failed to push changes to remote repository. This might be due to:"
                        Write-Host "- Repository requiring pull requests for changes" -ForegroundColor Yellow
                        Write-Host "- Insufficient push permissions" -ForegroundColor Yellow
                        Write-Host "- Branch protection rules" -ForegroundColor Yellow
                        Write-Host "Changes have been committed locally. You may need to create a pull request." -ForegroundColor Cyan
                        return $false
                    }
                } else {
                    Write-Warning "Failed to commit changes. This might be due to:"
                    Write-Host "- Git configuration issues (user.name/user.email)" -ForegroundColor Yellow
                    Write-Host "- Pre-commit hooks failing" -ForegroundColor Yellow
                    return $false
                }
            } else {
                Write-Warning "Failed to add file to Git. Check file permissions and Git status."
                return $false
            }
        } else {
            Write-Host "No changes detected in file: $relativePath"
            return $true
        }
    }
    catch {
        Write-Error "Error during Git operations: $($_.Exception.Message)"
        Write-Host "Stack trace: $($_.ScriptStackTrace)" -ForegroundColor Red
        return $false
    }
}

Import-Module -Name "./modules/pipelineFunctions.psm1"
Import-Dependencies

$jsonParameters1 = Get-Content -Path $bicepPar1 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters1

$jsonParameters2 = Get-Content -Path $bicepPar2 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters2

$jsonParameters3 = Get-Content -Path $bicepPar3 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters3

$jsonParameters4 = Get-Content -Path $bicepPar4 | ConvertFrom-Json
Set-DeployedOnTag -InputObject $jsonParameters4
ConvertTo-Variables -InputObject $jsonParameters4

$jsonParameters5 = Get-Content -Path $bicepPar5 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters5

## $tenantId comes from Parameters.json  - the rest is INPUT, as ADO parameters (see top of file)

if ( $useServicePrincipal -eq $null -or $useServicePrincipal -eq "" -or $useServicePrincipal -eq $false )
{
    $useServicePrincipal = $false
}
else
{
    $authSettings = @{
        useServicePrincipal = $useServicePrincipal
        tenantId            = $tenantId
        spObjId             = $spObjId
        spSecret            = $spSecret
        subscriptionId      = $subscriptionId
    }

    Connect-AzureContext @authSettings
}

if ($null -ne $commonRGNamePrefixVar -and $commonRGNamePrefixVar -ne '') {
    $commonRGNamePrefix = $commonRGNamePrefixVar
}
if ($null -ne $locationSuffixADO -and $locationSuffixADO -ne '') {
    $locationSuffix = $locationSuffixADO
}
if ($null -ne $aifactorySuffixRGADO -and $aifactorySuffixRGADO -ne '') {
    $aifactorySuffix = $aifactorySuffixRGADO
}

$templateName = "dynamicNetworkParams.json"
$deploymentPrefix = "esml-p$projectNumber-$env-$locationSuffix$aifactorySuffix" # esml-p001-dev-sdc-002

write-host "PARAMETERS: Static and Dynamic used::"
write-host "-STATIC (vnetResourceGroup): Static parameters: [commonRGNamePrefix,vnetResourceGroupBase, locationSuffix] (from PARAMETERS.json)"
write-host "-DYNAMIC (vnetResourceGroup): Dynamic parameters as INPUT (from ADO parameters UI): [env,locationSuffixADO,aifactorySuffixRGADO] this Powershell generates(dynamicNetworkParams.json)"

#$vnetResourceGroup =  "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffixADO-$env$aifactorySuffixRGADO" # msft[esml-common]-swc-dev-001

$vnetResourceGroup = if ( $null -eq $vnetResourceGroup_param -or "" -eq $vnetResourceGroup_param )
{
    "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffix-$env$aifactorySuffix"
}
else {
    if ( $null -eq $network_env -or "" -eq $network_env )
    {
        $vnetResourceGroup_param
    }
    else { 
        $vnetResourceGroup_param -replace '<network_env>', $network_env # Replace <network_env> placeholder with actual network_env value
    }
    
}

write-host "RESULT (vnetResourceGroup): $($vnetResourceGroup)"
write-host "Deployment to lookup (earlier subnets): $($deploymentPrefix)SubnetDeplProj" # Deployment to lookup (earlier subnets): esml-p001-dev-swc-001SubnetDeplProj

# First, normalize the BYO_subnets parameter since it's a string
$BYO_subnets_bool = if ($null -eq $BYO_subnets -or "" -eq $BYO_subnets -or $BYO_subnets -eq "false") {
    $false
} else {
    $true
}

$aksSubnetId=""
$dbxPubSubnetName=""
$dbxPrivSubnetName=""
$genaiSubnetId=""
$acaSubnetId=""

# Check if BYO_subnets is false
if ($BYO_subnets_bool -eq $false) {

    write-host "The following parameters are added to template"

    write-host "Project type all :  trying to fetch deployment with name: $($deploymentPrefix)SubnetDeplProj for AKS name"
    $aksSubnetId=(Get-AzResourceGroupDeployment `
    -ResourceGroupName "$vnetResourceGroup" `
    -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.aksSubnetId.Value

    if ([string]::IsNullOrEmpty($aksSubnetId)) {
        Write-Host "##vso[task.logissue type=warning]AksSubnetId is null or empty. This will likely cause deployment issues. Please delete the 3 project subnets (snt-prj001-genai,snt-prj001-aks,snt-prj001-aca), and set runNetworkingVar=True again."
        Write-Host "You may need to clean your project resource group first:"
        Write-Host "- 1) Azure portal: Delete all service in the resource group except keyvault. The private endpoint for keyvault is blocking deletion of a subnet."
        Write-Host "- 2) Azure portal: Delete the 3 or more subnets(snt-prj001-genai,snt-prj001-aks,snt-prj001-aca) in the COMMON resource group"
        Write-Host "- 3) ADO variable.yaml: Remove the value in the variable aifactory_salt_random in ADO variable.yaml"
        Write-Host "- 4) Azure portal:recreate the private endpoint later,after deployment, manually. Example name of pend: kv-p00X-eus2-dev-qoygy01-pend."
        Write-Host "- 5) POST deployment, add the value to variable aifactory_salt_random"
    

        # A) Fail the pipeline when aksSubnetId is missing:
        # Write-Host "##vso[task.complete result=Failed;]AksSubnetId is null or empty. The AKS deployment will fail without a valid subnet ID."
        #
        # B) provide a default or dummy value to allow the template to be created
        $aksSubnetId = "MISSING_REQUIRED_SUBNET_ID"
        exit 1
    }

    if($projectTypeADO.Trim().ToLower() -eq "esml"){
        write-host "Project type: esml - trying to fetch deployment with name: $($deploymentPrefix)SubnetDeplProj"

        $dbxPubSubnetName=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.dbxPubSubnetName.value

        $dbxPrivSubnetName=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.dbxPrivSubnetName.value
        
        write-host "dbxPubSubnetName: $dbxPubSubnetName"
        write-host "dbxPrivSubnetName: $dbxPrivSubnetName"
        write-host "aksSubnetId: $aksSubnetId"
    }elseif($projectTypeADO.Trim().ToLower() -eq "genai-1"){
        
        write-host "Project type: genai-1 - trying to fetch deployment with name: $($deploymentPrefix)SubnetDeplProj"
        
        $genaiSubnetId=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.genaiSubnetId.Value
        write-host "genaiSubnetId: $genaiSubnetId"
        write-host "aksSubnetId: $aksSubnetId"

        $acaSubnetId=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.acaSubnetId.Value
        write-host "acaSubnetId: $acaSubnetId"
    }
    else
    {
        write-host "Unsupported projectTypeADO value: '$projectTypeADO'"
    }

}else {
    <# Action when all if and elseif conditions are false #>
    # Replace placeholders in vnet and subnet names
    $vnetName = $vnetNameFull_param -replace '<network_env>', $network_env

    if ($null -ne $subnetCommon -and $subnetCommon -ne "") {
        # Common subnets
        $subnetCommonId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetCommon -networkEnv $network_env
        $subnetCommonScoringId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetCommonScoring -networkEnv $network_env
        $subnetCommonPowerbiGwId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetCommonPowerbiGw -networkEnv $network_env

        write-host "COMMON subnets: Just FYI - since these are specified directly in BICEP"
        write-host "subnetCommonId: $subnetCommonId"
        write-host "subnetCommonScoringId: $subnetCommonScoringId"
        write-host "subnetCommonPowerbiGwId: $subnetCommonPowerbiGwId"
    }

    if($projectTypeADO.Trim().ToLower() -eq "esml"){

        write-host "Project type: esml - now generating subnet IDs for AKS and Databricks, via in-parameters BYOSnets"
        if ($null -ne $subnetProjAKS -and $subnetProjAKS -ne "") {
            # ESML project subnets
            $aksSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjAKS -projectNumber $projectNumber -networkEnv $network_env

            $dbxPubSubnetName = $subnetProjDatabricksPublic -replace '<network_env>', $network_env
            $dbxPrivSubnetName = $subnetProjDatabricksPrivate -replace '<xxx>', $projectNumber

            # These can be full IDs if needed
            $dbxPubSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjDatabricksPublic -projectNumber $projectNumber -networkEnv $network_env
            $dbxPrivSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjDatabricksPrivate -projectNumber $projectNumber -networkEnv $network_env

            write-host "Databricks: Only the name is needed. Just FYI:"
            write-host "dbxPubSubnetId: $dbxPubSubnetId"
            write-host "dbxPrivSubnetId: $dbxPrivSubnetId"

            write-host "AKS full resoiurce ID, and Databrick subnet names:"
            write-host "aksSubnetId: $aksSubnetId"
            write-host "dbxPubSubnet Name: $dbxPubSubnetName"
            write-host "dbxPrivSubnet Name: $dbxPrivSubnetName"
        }
        else {
            write-host "AIF-WARNING:BYOSubnets:subnetProjAKS is not set. This is needed for AKS deployment. Please check your parameters.json file."
       }

    }

    if($projectTypeADO.Trim().ToLower() -eq "genai-1"){
        write-host "Project type: genai-1 : now generating subnet IDs for AKS and GenAI, via in-parameters BYOSnets"

        if ($null -ne $subnetProjGenAI -and $subnetProjGenAI -ne "") {
            $genaiSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjGenAI -projectNumber $projectNumber -networkEnv $network_env
            write-host "genaiSubnetId: $genaiSubnetId"

            try {
                $aksSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjAKS -projectNumber $projectNumber -networkEnv $network_env
                write-host "aksSubnetId: $aksSubnetId"    
            }
            catch {
                write-host "AIF-WARNING: aksSubnetId could not be generated. Please check your parameters.json file."    
            }

            try {
                $acaSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjACA -projectNumber $projectNumber -networkEnv $network_env
                write-host "acaSubnetId: $acaSubnetId"
            }
            catch {
                write-host "AIF-WARNING: acaSubnetId could not be generated. Please check your parameters.json file."    
            }
        }
    }
    else {
        write-host "AIF-WARNING:BYOSubnets:subnetProjGenAI: subnetProjGenAI is not set. This is needed for GenAI deployment. Please check your parameters.json file."
   }
}

$templateEsml = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "dbxPubSubnetName": {
            "value": "$dbxPubSubnetName"
        },
        "dbxPrivSubnetName": {
            "value": "$dbxPrivSubnetName"
        },
        "aksSubnetId": {
            "value": "$aksSubnetId"
        }
    }
}
"@

$templateGenaI = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "aksSubnetId": {
            "value": "$aksSubnetId"
        },
        "genaiSubnetId": {
            "value": "$genaiSubnetId"
        },
        "acaSubnetId": {
            "value": "$acaSubnetId"
        }
    }
}
"@

$template = "not set"

if($projectTypeADO.Trim().ToLower() -eq "esml"){
    write-host "Template for dynamicNetworkParams.json is projectType:esml"
    $template = $templateEsml
}
elseif ($projectTypeADO.Trim().ToLower() -eq "genai-1"){
    write-host "Template for dynamicNetworkParams.json is projectType:genai-1"
    $template = $templateGenaI
}
else{
    write-host "Template for dynamicNetworkParams.json is projectType:unsupported value: '$projectTypeADO'"
    $template = $templateEsml
}
$outputPath = "$filePath/$templateName".Replace('\', '/')
$template | Out-File $outputPath
write-host "Template written to $outputPath"

# Conditionally save to Git repository if requested
if ($saveFileInADOGitRepo -eq $true) {
    Write-Host "saveFileInADOGitRepo is enabled. Attempting to save file to Git repository..."
    
    try {
        $commitMessage = "Update dynamicNetworkParams.json for project $projectNumber environment $env ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))"
        
        # First, ensure we have the latest changes from remote
        Write-Host "Pulling latest changes from remote repository..."
        git pull origin HEAD --no-rebase 2>&1 | Out-Host
        
        $gitSaveResult = Save-FileToGitRepository -FilePath $outputPath -CommitMessage $commitMessage
        
        if ($gitSaveResult) {
            Write-Host "SUCCESS: File successfully saved to Git repository and can be verified in your repo" -ForegroundColor Green
        } else {
            Write-Warning "PARTIAL SUCCESS: File created locally at $outputPath but could not be saved to Git repository"
            Write-Host "You can manually verify the file content and commit it to your repository"
            Write-Host "Common reasons for Git save failures:" -ForegroundColor Yellow
            Write-Host "- No changes to commit (file already exists with same content)" -ForegroundColor Yellow
            Write-Host "- Insufficient permissions to push to repository" -ForegroundColor Yellow
            Write-Host "- Repository requires pull request workflow" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Warning "Git repository save encountered an error, but this will not fail the task."
        Write-Host "Error details: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "File has been successfully created locally at: $outputPath" -ForegroundColor Green
        Write-Host "You can manually commit and push this file to your repository later." -ForegroundColor Cyan
    }
} else {
    Write-Host "saveFileInADOGitRepo is disabled. File saved locally only at: $outputPath"
    Write-Host "To enable Git repository save, set parameter -saveFileInADOGitRepo `$true"
}