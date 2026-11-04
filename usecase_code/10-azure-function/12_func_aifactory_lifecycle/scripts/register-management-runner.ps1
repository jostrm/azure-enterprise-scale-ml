#Requires -Version 7.0
<#
.SYNOPSIS
  Register the management VM as a self-hosted runner for one factory repository (run from the laptop).

.DESCRIPTION
  Gets a one-hour registration token with your gh login (repo admin rights needed) and runs
  install-github-runner.ps1 on the VM through an Azure VM run command, passing the token as a protected parameter so
  it is not returned by the run-command API. The run command is deleted afterwards. The VM must be running.

.EXAMPLE
  .\register-management-runner.ps1 -Repository jostrm/azure-enterprise-scale-byor-121 `
      -SubscriptionId <sub> -ResourceGroup spider-esml-common-sdc-dev-001 -VmName dsvm-cmn-sdc-dev-001
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')] [string] $Repository,
    [Parameter(Mandatory)] [string] $SubscriptionId,
    [Parameter(Mandatory)] [string] $ResourceGroup,
    [Parameter(Mandatory)] [string] $VmName,
    [string] $Labels = 'aif-lifecycle-mgmt',
    [string] $RunnerName
)

$ErrorActionPreference = 'Stop'
$repositoryName = $Repository.Split('/')[1]
if (-not $RunnerName) { $RunnerName = "$VmName-$repositoryName" }
$script = Join-Path $PSScriptRoot 'install-github-runner.ps1'
$command = "aif-runner-$repositoryName"

# Filter in PowerShell: JMESPath functions with parentheses break through az.cmd on Windows.
$statuses = az vm get-instance-view --subscription $SubscriptionId -g $ResourceGroup -n $VmName `
    --query instanceView.statuses -o json | ConvertFrom-Json
$power = ($statuses | Where-Object { $_.code -like 'PowerState/*' } | Select-Object -First 1).code
if ($power -ne 'PowerState/running') { throw "$VmName is $power; start it first." }

if (-not $PSCmdlet.ShouldProcess("$VmName", "Register a runner for $Repository with labels $Labels")) { return }
$token = gh api -X POST "repos/$Repository/actions/runners/registration-token" --jq .token
if (-not $token) { throw 'Could not get a runner registration token (repo admin rights needed).' }
try {
    az vm run-command create --subscription $SubscriptionId -g $ResourceGroup --vm-name $VmName --name $command `
        --script "@$script" --async-execution false --timeout-in-seconds 1200 --output none `
        --parameters "RepositoryUrl=https://github.com/$Repository" "RunnerName=$RunnerName" "Labels=$Labels" `
        --protected-parameters "RegistrationToken=$token"
    $view = az vm run-command show --subscription $SubscriptionId -g $ResourceGroup --vm-name $VmName --name $command `
        --instance-view -o json | ConvertFrom-Json
    Write-Host "Run command: $($view.instanceView.executionState), exit code $($view.instanceView.exitCode)"
    Write-Host $view.instanceView.output
    if ($view.instanceView.error) { Write-Warning $view.instanceView.error }
}
finally {
    Remove-Variable token
    az vm run-command delete --subscription $SubscriptionId -g $ResourceGroup --vm-name $VmName --name $command --yes --output none
}
gh api "repos/$Repository/actions/runners" --jq '.runners[] | "\(.name) \(.status) [\([.labels[].name] | join(","))]"'
