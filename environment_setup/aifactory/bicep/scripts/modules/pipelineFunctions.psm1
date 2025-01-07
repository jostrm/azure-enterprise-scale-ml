#   - This module serves a bunch of shared methods that other scripts can use
#     and was intended to reduce DRY code in other scripts. Script is specifically designed 
#     to be a part of the ESML project template automation scripts.

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
            Install-Module Az.Resources -MinimumVersion $azResourcesVersion -Scope AllUsers -Force
            Install-Module Az.Network -MinimumVersion $azNetworkVersion -Scope AllUsers -Force
            Import-Module Az.Resources
            Import-Module Az.Accounts
            Import-Module Az.Network
         }
        "subnetCalc.ps1" { 
            Write-Verbose "Installing dependencies for $callingScriptName"
            Install-Module Az.Resources -MinimumVersion $azResourcesVersion -Scope AllUsers -Force
            Install-Module Az.Network -MinimumVersion $azNetworkVersion -Scope AllUsers -Force
            Install-Module Subnet -MinimumVersion $subnetVersion -Scope AllUsers -Force
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