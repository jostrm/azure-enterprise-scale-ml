#Requires -Version 7.0
<#
.SYNOPSIS
    Registers the Microsoft Entra app that App Service authentication uses for the lifecycle Function's routes.

.DESCRIPTION
    Creates (or updates) a single-tenant app with:
    - the app role Lifecycle.Operator (users and applications), which the Function requires (AIF_REQUIRED_ROLE);
    - identifier URI api://<appId> and v2 access tokens;
    - one delegated scope pre-authorized for Azure CLI, so an operator gets a token with
      `az account get-access-token --resource api://<appId>` without a consent prompt;
    and assigns the role to the users given in -Operator. Re-running keeps existing IDs.
    Then set authClientId in settings.<consumer>.json and AIF_REQUIRED_ROLE=Lifecycle.Operator in its appSettings.

.EXAMPLE
    .\register-entra-app.ps1 -DisplayName aif-lifecycle-func-spider -Operator someone@contoso.onmicrosoft.com
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$DisplayName,
    [string[]]$Operator = @(),
    [string]$Role = 'Lifecycle.Operator'
)
$ErrorActionPreference = 'Stop'
$azureCli = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'  # Azure CLI's well-known client ID

function Invoke-Graph([string]$Method, [string]$Uri, $Body) {
    $arguments = @('rest', '--method', $Method, '--uri', "https://graph.microsoft.com/v1.0$Uri", '--output', 'json')
    $file = $null
    if ($null -ne $Body) {
        $file = New-TemporaryFile
        $Body | ConvertTo-Json -Depth 10 -Compress | Set-Content -LiteralPath $file -Encoding utf8NoBOM -WhatIf:$false
        $arguments += @('--body', "@$file", '--headers', 'Content-Type=application/json')
    }
    try {
        $output = az @arguments
        if ($LASTEXITCODE -ne 0) { throw "Graph $Method $Uri failed." }
        if ($output) { return $output | ConvertFrom-Json }
    } finally {
        if ($file) { Remove-Item -LiteralPath $file -WhatIf:$false }
    }
}

$app = (Invoke-Graph GET "/applications?`$filter=displayName eq '$DisplayName'").value | Select-Object -First 1
if (-not $app) {
    if (-not $PSCmdlet.ShouldProcess($DisplayName, 'Create app registration')) { return }
    $app = Invoke-Graph POST '/applications' @{ displayName = $DisplayName; signInAudience = 'AzureADMyOrg' }
}
$roleId = ($app.appRoles | Where-Object value -eq $Role | Select-Object -First 1).id ?? [guid]::NewGuid().ToString()
$scope = $app.api.oauth2PermissionScopes | Where-Object value -eq 'user_impersonation' | Select-Object -First 1
$scopeId = $scope.id ?? [guid]::NewGuid().ToString()
$appRoles = @($app.appRoles | Where-Object value -ne $Role) + @{
    id = $roleId; value = $Role; displayName = 'Lifecycle operator'; isEnabled = $true
    allowedMemberTypes = @('User', 'Application')
    description = 'Prepare, confirm and read AI Factory lifecycle operations.'
}
if ($PSCmdlet.ShouldProcess($DisplayName, "Set role $Role, api://$($app.appId) and the Azure CLI scope")) {
    Invoke-Graph PATCH "/applications/$($app.id)" @{
        identifierUris = @("api://$($app.appId)")
        appRoles = $appRoles
        api = @{
            requestedAccessTokenVersion = 2
            oauth2PermissionScopes = @(@{
                id = $scopeId; value = 'user_impersonation'; type = 'User'; isEnabled = $true
                adminConsentDisplayName = 'Call the lifecycle Function'; adminConsentDescription = 'Call the AI Factory lifecycle Function as the signed-in user.'
                userConsentDisplayName = 'Call the lifecycle Function'; userConsentDescription = 'Call the AI Factory lifecycle Function as you.'
            })
        }
    } | Out-Null
    # Graph refuses to pre-authorize a scope in the request that creates it, so this is a second call.
    Invoke-Graph PATCH "/applications/$($app.id)" @{
        api = @{ preAuthorizedApplications = @(@{ appId = $azureCli; delegatedPermissionIds = @($scopeId) }) }
    } | Out-Null
}

$sp = (Invoke-Graph GET "/servicePrincipals?`$filter=appId eq '$($app.appId)'").value | Select-Object -First 1
if (-not $sp -and $PSCmdlet.ShouldProcess($app.appId, 'Create service principal')) {
    $sp = Invoke-Graph POST '/servicePrincipals' @{ appId = $app.appId; appRoleAssignmentRequired = $true }
}
foreach ($name in $Operator) {
    $user = Invoke-Graph GET "/users/$([uri]::EscapeDataString($name))?`$select=id"
    $assigned = (Invoke-Graph GET "/servicePrincipals/$($sp.id)/appRoleAssignedTo").value |
        Where-Object { $_.principalId -eq $user.id -and $_.appRoleId -eq $roleId }
    if (-not $assigned -and $PSCmdlet.ShouldProcess($name, "Assign $Role")) {
        Invoke-Graph POST "/servicePrincipals/$($sp.id)/appRoleAssignedTo" @{
            principalId = $user.id; resourceId = $sp.id; appRoleId = $roleId } | Out-Null
    }
}
[pscustomobject]@{ authClientId = $app.appId; role = $Role; audience = "api://$($app.appId)" }
