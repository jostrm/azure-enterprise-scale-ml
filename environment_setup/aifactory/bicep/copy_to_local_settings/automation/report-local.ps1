param([Parameter(Mandatory)][string]$RequestPath)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json -AsHashtable
$scripts = @{
    'foundry-tokens' = 'coreteam\finops\runbooks\Update-FoundryTokenReport.ps1'
    'showback' = 'coreteam\finops\runbooks\showback\Update-ShowbackReport.ps1'
}
try {
    if ($request.version -ne 1 -or $request.compute -ne 'local' -or -not $scripts.ContainsKey($request.report_type)) {
        throw 'Unsupported local report request.'
    }
    $target = $request.target
    if (-not $request.dry_run) {
        if (-not (Get-Module -ListAvailable Az.Accounts)) { throw 'Az.Accounts is required for live PowerShell reports.' }
        Import-Module Az.Accounts -WarningAction SilentlyContinue
        Disable-AzContextAutosave -Scope Process | Out-Null
        $context = Get-AzContext
        if (-not $context -or $context.Subscription.Id -ne $target.subscription_id -or $context.Tenant.Id -ne $target.tenant_id) {
            throw 'Current Az PowerShell subscription/tenant does not match the selected target. Sign in/select that context first.'
        }
    }
    $arguments = @{
        SubscriptionId=$target.subscription_id; TenantId=$target.tenant_id
        ProjectNumber=$target.project_number; Env=$target.environment
        ProjectResourceGroup=$target.project_resource_group; CommonResourceGroup=$target.common_resource_group
        ConfigJson=($request.report_config | ConvertTo-Json -Depth 30 -Compress)
        LookbackDays=$request.days; NoUpload=$true; ReportFormat='Json'; UseCurrentLogin=$true
        DryRun=[bool]$request.dry_run
    }
    & (Join-Path $PSScriptRoot $scripts[$request.report_type]) @arguments
} catch {
    # Do not return command text or exception bodies that might contain configuration secrets.
    $message = 'Local report failed. Check the exact Az PowerShell subscription/tenant, optional Az modules, report configuration and resource access.'
    if ($_.Exception.Message -like 'Current Az PowerShell*') { $message = $_.Exception.Message }
    [ordered]@{
        status='failed'; source=$(if ($request.dry_run) {'sample'} else {'live'}); compute='local'
        run_id=$null; output=$message; report=$null; warnings=@($message)
    } | ConvertTo-Json -Depth 10 -Compress
    exit 1
}
