
# If AI Factory Project-Networking fails 04_pwsh_calculate_subnet_allocations (subnetCalc.ps1). Try below: 

# Solution 1) Many times version needs to be synced
# Solution 2)  -AllowClobber in this file was latest solution, after Install-Module. When '4.248.1' This works on other pipeline, but 4.251.1 was used. (Then AllowClobber worked)
# Solution 3) Change version in the pipeline YAML file. Both 'OtherVersion' and 'preferredAzurePowerShellVersion' needs to be set.
#   azurePowerShellVersion: 'LatestVersion' # 'LatestVersion' | 'OtherVersion' 
#  preferredAzurePowerShellVersion: # ['4.251.1',' 5.251.1'] is downloaded, see TASK 'Initialize job'. 

# Solution 5) Not tested. Since the buildagent could not download'4.248.1', maybe the below will work. 
# [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
# Register-PSRepository -Default -Verbose
# Set-PSRepository -Name "PSGallery" -InstallationPolicy Trusted

#Import-Module Az

function Connect-AzureContext {
    param (
        [Parameter(Mandatory=$true, HelpMessage="Use service principal")][switch]$useServicePrincipal=$false,
        [Parameter(Mandatory=$false, HelpMessage="Specifies the tenantId")][string]$tenantId,
        [Parameter(Mandatory=$false, HelpMessage="Specifies the object id for service principal")][string]$spObjId,
        [Parameter(Mandatory=$false, HelpMessage="Specifies the secret for service principal")][string]$spSecret,
        [Parameter(Mandatory=$false, HelpMessage="Specifies subscriptionId for deployment")][string]$subscriptionId
    )
    if ($useServicePrincipal){
        Write-host "Service principal authentication enabled"
    
        $azureAplicationId = $spObjId
        $azureTenantId = $tenantId
        $azurePassword = ConvertTo-SecureString $spSecret -AsPlainText -Force
        $psCred = New-Object System.Management.Automation.PSCredential($azureAplicationId , $azurePassword)
    
        Connect-AzAccount -Credential $psCred -TenantId $azureTenantId  -ServicePrincipal -WarningAction SilentlyContinue # it will tell us to use set-context
        Set-AzContext -SubscriptionId $subscriptionId # which we do here!
        
        # if verbose flag is enabled
        Write-Verbose "servicePrincipalId: $azureAplicationId"
        Write-Verbose "tenantId: $azureTenantId"
        Write-Verbose "SubscriptionId: $SubscriptionId"
    } else {
        Write-host "Using current context active AzContext"
    }
}

function ConvertTo-Variables {
    # Read an ARM template parameters file and set convert the parameters contents to global variables
    [CmdletBinding()]
    [OutputType('hashtable')]
    param (
        [Parameter(ValueFromPipeline)]
        $InputObject
    )
    process {
        $hashtable = @{}
        foreach ($parameter in ($InputObject.parameters | Get-Member *)){
            if ($parameter.MemberType -eq "NoteProperty") {
                Set-Variable -Scope "Global" -Value $InputObject.parameters.($parameter.Name).value -Name $parameter.Name
            }
        }
        $hashtable
    }
}

function Import-Dependencies {
    $callingScriptName = (Get-PSCallStack)[1].Command
    $azResourcesVersion="4.3.0"
    $azNetworkVersion="4.10.0"
    $subnetVersion="1.0.6"
    switch ($callingScriptName) {
        "generateUserParameters.ps1" { 
            Write-Verbose "(disabled due to DEMO env, no AD permission to lookup username) Installing dependencies for $callingScriptName"
            #Write-Verbose "Installing dependencies for $callingScriptName"
            #Install-Module Az.Resources -MinimumVersion $azResourcesVersion -Scope AllUsers -Force
            #Import-Module Az.Resources
            #Import-Module Az.Accounts
         }
        "genDynamicNetworkParamFile.ps1" { 
            Write-Verbose "Installing dependencies for $callingScriptName"
            Install-Module Az.Resources -MinimumVersion $azResourcesVersion -Scope AllUsers -Force -AllowClobber
            Install-Module Az.Network -MinimumVersion $azNetworkVersion -Scope AllUsers -Force -AllowClobber
            Import-Module Az.Resources
            Import-Module Az.Accounts
            Import-Module Az.Network
         }
        "subnetCalc.ps1" { 
            Write-Verbose "Installing dependencies for $callingScriptName"
            Install-Module Az.Resources -MinimumVersion $azResourcesVersion -Scope AllUsers -Force -AllowClobber
            Install-Module Az.Network -MinimumVersion $azNetworkVersion -Scope AllUsers -Force -AllowClobber
            Install-Module Subnet -MinimumVersion $subnetVersion -Scope AllUsers -Force -AllowClobber
            Import-Module Az.Resources
            Import-Module Az.Accounts
            Import-Module Az.Network
            Import-Module Subnet
        }
        "subnetCalc_v2.ps1" { 
            Write-Verbose "Installing dependencies for $callingScriptName"
            Install-Module Az.Resources -MinimumVersion $azResourcesVersion -Scope AllUsers -Force -AllowClobber
            Install-Module Az.Network -MinimumVersion $azNetworkVersion -Scope AllUsers -Force -AllowClobber
            Install-Module Subnet -MinimumVersion $subnetVersion -Scope AllUsers -Force -AllowClobber
            Import-Module Az.Resources
            Import-Module Az.Accounts
            Import-Module Az.Network
            Import-Module Subnet
        }
        Default {
            Write-Error "Sorry, could not match caller name with any switch conditions..."
        }
    }
}

# Utility: strip network environment prefix from subnet IDs (used by genDynamicNetworkParamFile.ps1)
function Remove-NetworkEnvPrefixFromSubnetId {
    param(
        [string]$subnetId,
        [string]$networkEnv
    )

    if ([string]::IsNullOrEmpty($subnetId) -or [string]::IsNullOrEmpty($networkEnv)) {
        return $subnetId
    }

    # networkEnv typically "dev-" / "test-" / "prod-". Remove that segment immediately after "subnets/snt-" if present.
    $pattern = "/subnets/snt-${networkEnv}"
    $replacement = '/subnets/snt-'
    return $subnetId -replace [regex]::Escape($pattern), $replacement
}