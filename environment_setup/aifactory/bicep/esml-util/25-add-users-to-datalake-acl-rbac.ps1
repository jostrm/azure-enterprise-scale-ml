# Preview by default. Uses the existing tenant-verified Azure CLI identity, never account keys.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid]$tenantID,
    [Parameter(Mandatory)][guid]$subscriptionID,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9]{3,24}$')][string]$storageAccount,
    [Parameter(Mandatory)][string]$storageResourceGroup,
    [string]$adlsgen2filesystem = 'lake3',
    [Parameter(Mandatory)][ValidatePattern('^project[0-9]{3}$')][string]$projectXXX,
    [ValidateSet('dev','test','prod')][string]$environment = 'dev',
    [string[]]$userObjectIds = @(),
    [string]$projectSPObjectID = '',
    [string]$projectADGroupObjectId = '',
    [string[]]$managedIdentityObjectIds = @(),
    [string[]]$readOnlyObjectIds = @(),
    [string]$commonSPObjectID = '',
    [string]$commonADgroupObjectID = '',
    [string]$spID = '',
    [string]$spSecret = '',
    [string]$PythonExecutable = 'python',
    [string]$ReceiptPath = '',
    [switch]$LegacyLayout,
    [switch]$TemporaryDataOwner,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
if ($spSecret) {
    throw 'Secret-based login was removed. Sign in with the approved Azure CLI workload/user identity before running this script.'
}
if (($commonSPObjectID -and $commonSPObjectID -notin @('TODO','NULL')) -or
    ($commonADgroupObjectID -and $commonADgroupObjectID -notin @('TODO','NULL'))) {
    throw 'Project onboarding must not change common-team ACLs. Configure common access separately.'
}
function Convert-ObjectIds([string[]]$Values) {
    $result = @()
    foreach ($value in $Values) {
        foreach ($item in ($value -split ',')) {
            if ($item.Trim() -and $item.Trim() -notin @('TODO','NULL')) {
                $result += ([guid]$item.Trim()).ToString()
            }
        }
    }
    return @($result | Sort-Object -Unique)
}
$users = @(Convert-ObjectIds $userObjectIds)
$identities = @(Convert-ObjectIds ($managedIdentityObjectIds + @($projectSPObjectID)))
$groups = @(Convert-ObjectIds @($projectADGroupObjectId))
$readers = @(Convert-ObjectIds $readOnlyObjectIds)
$request = @{
    tenant_id = $tenantID.ToString(); subscription_id = $subscriptionID.ToString()
    storage_account = $storageAccount; resource_group = $storageResourceGroup
    filesystem = $adlsgen2filesystem; project = $projectXXX; environment = $environment
    users = $users; groups = $groups; managed_identities = $identities; readers = $readers
    legacy_layout = [bool]$LegacyLayout; temporary_data_owner = [bool]$TemporaryDataOwner
    execute = [bool]$Execute; receipt_path = $ReceiptPath
}
$helper = Join-Path $PSScriptRoot 'project_lake_access.py'
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw "Required helper missing: $helper" }
$request | ConvertTo-Json -Depth 8 -Compress | & $PythonExecutable $helper
if ($LASTEXITCODE -ne 0) { throw "Project lake access failed (exit $LASTEXITCODE); inspect its receipt before retrying." }
