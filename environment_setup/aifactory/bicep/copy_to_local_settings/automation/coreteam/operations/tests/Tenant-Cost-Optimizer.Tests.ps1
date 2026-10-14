#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.7.1' }

BeforeAll {
    $runtime = Join-Path (Split-Path $PSScriptRoot -Parent) 'Tenant-Cost-Optimizer.ps1'
    . $runtime
    $script:RealComplete = ${function:Test-TargetActionComplete}
    $script:RealSave = ${function:Save-OptimizerState}
    $script:RealArm = ${function:Invoke-ArmRequest}
    function Get-AutomationVariable { param([string]$Name) throw 'Automation variable must be mocked.' }

    function New-TestConfiguration {
        param([ValidateSet('One', 'Two')][string]$Customer = 'One', [int]$TargetCount = 8)
        $tenant = if ($Customer -eq 'One') { '11111111-1111-4111-8111-111111111111' } else { '22222222-2222-4222-8222-222222222222' }
        $subscription = if ($Customer -eq 'One') { 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' } else { 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' }
        $prefix = "customer-$($Customer.ToLowerInvariant())"
        $common = "$prefix-esml-common-weu-dev-001"
        $project = "$prefix-esml-project001-weu-dev-001-rg"
        $targets = @(
            @{ kind = 'ContainerApp'; id = "/subscriptions/$subscription/resourceGroups/$project/providers/Microsoft.App/containerApps/agent-dev" }
            @{ kind = 'ContainerApp'; id = "/subscriptions/$subscription/resourceGroups/$project/providers/Microsoft.App/containerApps/mcp-dev" }
            @{ kind = 'ContainerApp'; id = "/subscriptions/$subscription/resourceGroups/$project/providers/Microsoft.App/containerApps/api-dev" }
            @{ kind = 'VirtualMachine'; id = "/subscriptions/$subscription/resourceGroups/$common/providers/Microsoft.Compute/virtualMachines/off-dev-vm" }
            @{ kind = 'VirtualMachine'; id = "/subscriptions/$subscription/resourceGroups/$common/providers/Microsoft.Compute/virtualMachines/runner-ado-weu-dev-001" }
            @{ kind = 'VirtualMachine'; id = "/subscriptions/$subscription/resourceGroups/$common/providers/Microsoft.Compute/virtualMachines/runner-gha-weu-dev-001" }
            @{ kind = 'VirtualMachine'; id = "/subscriptions/$subscription/resourceGroups/$common/providers/Microsoft.Compute/virtualMachines/worker-dev-vm" }
            @{ kind = 'VirtualMachine'; id = "/subscriptions/$subscription/resourceGroups/$common/providers/Microsoft.Compute/virtualMachines/failure-dev-vm" }
        )
        $configuration = @{
            schemaVersion = 2
            tenantId = $tenant
            subscriptionId = $subscription
            location = 'westeurope'
            resourceGroup = if ($Customer -eq 'One') { 'aif-cost-opt-111122223333-rg' } else { 'aif-cost-opt-444455556666-rg' }
            automationAccount = if ($Customer -eq 'One') { 'aa-aif-cost-opt-111122223333' } else { 'aa-aif-cost-opt-444455556666' }
            runbookName = 'Tenant-Cost-Optimizer'
            runtimeName = 'CostOptimizer-PowerShell76'
            configurationVariable = 'CostOptimizerConfiguration'
            stateStorageAccount = if ($Customer -eq 'One') { 'staifcost111122223333' } else { 'staifcost444455556666' }
            stateContainer = 'cost-optimizer-state'
            stateTransport = 'ArmContainerMetadata'
            timeZone = 'Europe/Stockholm'
            firstStop = '2026-10-10T03:00:00+02:00'
            firstStart = '2026-10-10T08:00:00+02:00'
            stopTime = '03:00'
            startTime = '08:00'
            stopSchedule = 'STOP-COST-OPTIMIZE-0300'
            startSchedule = 'START-COST-OPTIMIZE-0800'
            operationTimeoutSeconds = 1200
            scope = @{
                factoryKey = if ($Customer -eq 'One') { '111122223333' } else { '444455556666' }
                environment = 'dev'
                resourceGroups = @($project, $common)
                variablesSha256 = 'a' * 64
            }
            targets = @($targets | Select-Object -First $TargetCount)
        }
        $configuration.planHash = Get-CostOptimizerPlanHash $configuration
        return $configuration
    }

    function Copy-TestConfiguration {
        param([hashtable]$Configuration = $script:TestConfiguration)
        return $Configuration | ConvertTo-Json -Depth 25 | ConvertFrom-Json -AsHashtable -DateKind String
    }

    function Set-TestPlanHash {
        param([hashtable]$Configuration)
        $Configuration.planHash = Get-CostOptimizerPlanHash $Configuration
    }

    $script:TestConfiguration = New-TestConfiguration

function New-TestApp {
    return @{
        properties = @{
            runningStatus = 'Running'
            latestRevisionName = 'revision-current'
            configuration = @{
                activeRevisionsMode = 'Single'
                ingress = @{ traffic = @(@{ latestRevision = $true; weight = 100 }) }
            }
        }
    }
}

function New-TestRevisions {
    return @(
        @{ name = 'revision-current'; properties = @{ active = $true; healthState = 'Healthy'; trafficWeight = 100; replicas = 1 } }
    )
}
}

Describe 'Tenant cost optimizer safety' {
    BeforeEach {
        $script:Configuration = Copy-TestConfiguration
        $script:Fingerprint = Get-ConfigurationFingerprint $script:Configuration
        $script:State = New-IdleState $script:Fingerprint
        $script:Mode = 'Live'
        $script:Lease = $null
        $script:Tokens = @{}
        $script:StateWriteUncertain = $false
        $script:CurrentJobId = [Guid]::NewGuid().ToString()
        $script:StateContainerUri = 'https://management.azure.com/example/container'
        $script:StateUri = 'https://example.blob.core.windows.net/state/checkpoint.json'
        Mock Save-OptimizerState {}
        Mock Invoke-WebRequest { throw 'No live HTTP is permitted in these tests.' }
        Mock Invoke-ArmRequest { return @{ json = (New-TestApp); status = 200 } }
        Mock Get-AppRevisions { return ,(New-TestRevisions) }
        Mock Get-VmPowerState {
            if ($Id -like '*/off-dev-vm') { return 'PowerState/deallocated' }
            return 'PowerState/running'
        }
        Mock Test-TargetActionComplete { return $true }
    }

    It 'accepts the customer-one reviewed app and VM allowlist' {
        { Assert-OptimizerConfiguration $script:Configuration } | Should -Not -Throw
        @($script:Configuration.targets | Where-Object kind -eq 'ContainerApp').Count | Should -Be 3
        @($script:Configuration.targets | Where-Object kind -eq 'VirtualMachine').Count | Should -Be 5
    }

    It 'rejects AKS or any unapproved resource' {
        $copy = ($script:Configuration | ConvertTo-Json -Depth 15) | ConvertFrom-Json -AsHashtable
        $copy.targets[0].id = $copy.targets[0].id.Replace('Microsoft.App/containerApps', 'Microsoft.ContainerService/managedClusters')
        { Assert-OptimizerConfiguration $copy } | Should -Throw
    }

    It 'rejects duplicate targets instead of silently omitting another VM' {
        $copy = ($script:Configuration | ConvertTo-Json -Depth 15) | ConvertFrom-Json -AsHashtable
        $copy.targets[7] = $copy.targets[6]
        { Assert-OptimizerConfiguration $copy } | Should -Throw
    }

    It 'does not claim or restore an already deallocated VM' {
        $snapshot = New-StopSnapshot
        $snapshot.targets.Count | Should -Be 8
        @($snapshot.targets | Where-Object shouldRestore).Count | Should -Be 7
        $offVm = @($snapshot.targets | Where-Object id -like '*/off-dev-vm')[0]
        $offVm.shouldRestore | Should -Be $false
        $offVm.status | Should -Be 'Skipped'
    }

    It 'uses application stop without changing Single revision mode' {
        $snapshot = New-StopSnapshot
        $app = @($snapshot.targets | Where-Object kind -eq 'ContainerApp')[0]
        Request-TargetAction -Entry $app -RequestedAction STOP
        Assert-MockCalled Invoke-ArmRequest -Times 1 -Exactly -ParameterFilter { $Method -eq 'Post' -and $Path -like '*/stop' }
        Assert-MockCalled Invoke-ArmRequest -Times 0 -Exactly -ParameterFilter { $Method -eq 'Put' -or $Path -like '*/deactivate' }
    }

    It 'refuses to resume an app replaced by a new deployment' {
        $snapshot = New-StopSnapshot
        $app = @($snapshot.targets | Where-Object kind -eq 'ContainerApp')[0]
        $app.stopAccepted = $true
        Mock Invoke-ArmRequest {
            $value = New-TestApp
            $value.properties.latestRevisionName = 'new-deployment'
            return @{ json = $value }
        }
        { Request-TargetAction -Entry $app -RequestedAction START } | Should -Throw
        Assert-MockCalled Invoke-ArmRequest -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }

    It 'does not overwrite the original snapshot on repeated STOP' {
        $script:State = New-StopSnapshot
        $originalCycle = $script:State.cycleId
        $script:State.phase = 'Stopped'
        Mock New-StopSnapshot { throw 'Repeated STOP must not take a new baseline.' }
        Mock Request-TargetAction {}
        $result = Invoke-StatefulAction STOP
        $result.phase | Should -Be 'Stopped'
        $script:State.cycleId | Should -Be $originalCycle
        Assert-MockCalled New-StopSnapshot -Times 0 -Exactly
    }

    It 'restores only the resources captured as running' {
        $script:State = New-StopSnapshot
        $script:State.phase = 'Stopped'
        foreach ($entry in $script:State.targets) {
            if ($entry.shouldRestore) {
                $entry.status = 'Stopped'
                $entry.stopAccepted = $true
            }
        }
        Mock Request-TargetAction {}
        $result = Invoke-StatefulAction START
        $result.phase | Should -Be 'Started'
        Assert-MockCalled Request-TargetAction -Times 7 -Exactly -ParameterFilter { $RequestedAction -eq 'START' }
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly -ParameterFilter { $Entry.id -like '*/off-dev-vm' }
    }

    It 'does not start anything without an outstanding STOP snapshot' {
        Mock Request-TargetAction {}
        $result = Invoke-StatefulAction START
        $result.phase | Should -Be 'Idle'
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        Assert-MockCalled Save-OptimizerState -Times 0 -Exactly
    }

    It 'does not claim snapshot targets whose STOP was never issued' {
        $script:State = New-StopSnapshot
        $script:State.phase = 'StopFailed'
        Mock Request-TargetAction {}
        $result = Invoke-StatefulAction START
        $result.phase | Should -Be 'Started'
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        @($script:State.targets | Where-Object status -eq 'Skipped').Count | Should -Be 8
    }

    It 'fails closed when an unconfirmed STOP could have powered a VM off' {
        $script:State = New-StopSnapshot
        $entry = @($script:State.targets | Where-Object id -like '*/runner-ado-weu-dev-001')[0]
        $entry.stopAttempted = $true
        $entry.status = 'StopFailed'
        $script:State.phase = 'StopFailed'
        Mock Get-VmPowerState { return 'PowerState/deallocated' }
        Mock Request-TargetAction {}
        { Invoke-StatefulAction START } | Should -Throw
        $script:State.phase | Should -Be 'StartFailed'
        $entry.error | Should -Match 'not confirmed'
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
    }

    It 'confirms app-level STOP even when original revision flags remain active' {
        $script:State = New-StopSnapshot
        $entry = @($script:State.targets | Where-Object kind -eq 'ContainerApp')[0]
        Mock Invoke-ArmRequest {
            $value = New-TestApp
            $value.properties.runningStatus = 'Stopped'
            return @{ json = $value }
        }
        Mock Get-AppRevisions {
            $revisions = @(New-TestRevisions)
            $revisions[0].properties.replicas = 0
            return ,$revisions
        }
        & $script:RealComplete -Entry $entry -RequestedAction STOP | Should -Be $true
    }

    It 'does not mislabel an attempted but unconfirmed VM STOP as skipped' {
        $snapshot = New-StopSnapshot
        $entry = @($snapshot.targets | Where-Object id -like '*/runner-ado-weu-dev-001')[0]
        $entry.stopAttempted = $true
        Mock Get-VmPowerState { return 'PowerState/deallocated' }
        { Request-TargetAction -Entry $entry -RequestedAction STOP } | Should -Throw '*not confirmed*'
        $entry.status | Should -Not -Be 'Skipped'
    }

    It 'does not mislabel an attempted but unconfirmed app STOP as skipped' {
        $snapshot = New-StopSnapshot
        $entry = @($snapshot.targets | Where-Object kind -eq 'ContainerApp')[0]
        $entry.stopAttempted = $true
        Mock Invoke-ArmRequest {
            $app = New-TestApp
            $app.properties.runningStatus = 'Stopped'
            return @{ json = $app }
        }
        { Request-TargetAction -Entry $entry -RequestedAction STOP } | Should -Throw '*not confirmed*'
        $entry.status | Should -Not -Be 'Skipped'
    }

    It 'records a partial STOP failure and preserves the original baseline' {
        $script:State = New-StopSnapshot
        $cycle = $script:State.cycleId
        Mock Request-TargetAction {
            if ($Entry.id -like '*/failure-dev-vm') { throw 'Simulated VM control failure.' }
        }
        { Invoke-StatefulAction STOP } | Should -Throw
        $script:State.phase | Should -Be 'StopFailed'
        $script:State.cycleId | Should -Be $cycle
        @($script:State.targets | Where-Object status -eq 'StopFailed').Count | Should -Be 1
        @($script:State.targets | Where-Object status -eq 'Stopped').Count | Should -Be 6
    }

    It 'blocks a fresh STOP while START recovery remains incomplete' {
        $script:State.phase = 'StartFailed'
        { Invoke-StatefulAction STOP } | Should -Throw
        Assert-MockCalled Save-OptimizerState -Times 0 -Exactly
    }

    It 'keeps Preview completely read-only' {
        $script:Mode = 'Preview'
        Mock Read-OptimizerState { return @{ exists = $false; data = (New-IdleState $script:Fingerprint) } }
        Mock Request-TargetAction {}
        $result = Get-OptimizerPreview STOP
        $result.targets.Count | Should -Be 8
        @($result.targets | Where-Object wouldStop).Count | Should -Be 7
        Assert-MockCalled Save-OptimizerState -Times 0 -Exactly
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
    }

    It 'handles expected Blob 404 XML without attempting JSON parsing' {
        Mock Get-ManagedIdentityToken { return 'test-token' }
        Mock Invoke-WebRequest {
            return @{ StatusCode = 404; Content = '<Error><Code>BlobNotFound</Code></Error>'; Headers = @{} }
        }
        $response = Invoke-OptimizerRequest -Uri $script:StateUri -Audience 'https://storage.azure.com/' -ExpectedStatuses @(404)
        $response.status | Should -Be 404
        ($null -eq $response.json) | Should -Be $true
    }

    It 'performs no HTTP operation after losing the checkpoint lease' {
        Mock Update-StateLease { throw 'Lease lost.' }
        Mock Invoke-WebRequest {}
        { Invoke-OptimizerRequest -Uri 'https://management.azure.com/example' -Method Post } | Should -Throw
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }

    It 'round-trips the complete compressed checkpoint inside the metadata limit' {
        $snapshot = New-StopSnapshot
        $encoded = ConvertTo-CheckpointMetadata $snapshot
        $encoded.Length | Should -BeLessThan 7000
        $decoded = ConvertFrom-CheckpointMetadata $encoded
        $decoded.cycleId | Should -Be $snapshot.cycleId
        $decoded.targets.Count | Should -Be 8
        @($decoded.targets | Where-Object shouldRestore).Count | Should -Be 7
    }

    It 'rejects corrupted metadata rather than returning an idle success-shaped state' {
        { ConvertFrom-CheckpointMetadata 'not-base64' } | Should -Throw
    }

    It 'does not reclaim a mutex held by a running job' {
        Mock Invoke-StateLeaseAction { return @{ status = 409; json = $null } }
        Mock Get-OptimizerJobHistory {
            return ,@(@{ properties = @{ status = 'Running'; lastModifiedTime = [DateTimeOffset]::UtcNow.AddMinutes(-20).ToString('o'); jobId = [Guid]::NewGuid().ToString() } })
        }
        { Enter-StateLease } | Should -Throw
        Assert-MockCalled Invoke-StateLeaseAction -Times 0 -Exactly -ParameterFilter { $Body.action -eq 'Release' }
    }

    It 'does not reclaim a terminal job still in its settling period' {
        Mock Invoke-StateLeaseAction { return @{ status = 409; json = $null } }
        Mock Get-OptimizerJobHistory {
            return ,@(@{ properties = @{ status = 'Failed'; lastModifiedTime = [DateTimeOffset]::UtcNow.AddMinutes(-2).ToString('o'); jobId = [Guid]::NewGuid().ToString() } })
        }
        { Enter-StateLease } | Should -Throw
        Assert-MockCalled Invoke-StateLeaseAction -Times 0 -Exactly -ParameterFilter { $Body.action -eq 'Release' }
    }

    It 'reclaims only the exact mutex of a settled terminal job' {
        $script:AcquireCount = 0
        $script:OldJobId = [Guid]::NewGuid().ToString()
        Mock Get-OptimizerJobHistory {
            return ,@(@{ properties = @{ status = 'Failed'; lastModifiedTime = [DateTimeOffset]::UtcNow.AddMinutes(-11).ToString('o'); jobId = $script:OldJobId } })
        }
        Mock Invoke-StateLeaseAction {
            if ($Body.action -eq 'Acquire') {
                $script:AcquireCount++
                if ($script:AcquireCount -eq 1) { return @{ status = 409; json = $null } }
                return @{ status = 200; json = @{ leaseId = $script:CurrentJobId } }
            }
            return @{ status = 200; json = @{} }
        }
        Mock Read-OptimizerState { return @{ exists = $false; data = (New-IdleState $script:Fingerprint) } }
        Enter-StateLease
        $script:Lease.id | Should -Be $script:CurrentJobId
        Assert-MockCalled Invoke-StateLeaseAction -Times 1 -Exactly -ParameterFilter {
            $Body.action -eq 'Release' -and $Body.leaseId -eq $script:OldJobId
        }
    }

    It 'does not record or release a lease identifier different from the proposed job identity' {
        Mock Invoke-StateLeaseAction { return @{ status = 200; json = @{ leaseId = [Guid]::NewGuid().ToString() } } }
        { Enter-StateLease } | Should -Throw '*proposed job-bound lease ID*'
        $script:Lease | Should -BeNullOrEmpty
        Exit-StateLease
        Assert-MockCalled Invoke-StateLeaseAction -Times 0 -Exactly -ParameterFilter { $Body.action -eq 'Release' }
    }

    It 'does not retry or release after an unknown checkpoint write outcome' {
        $script:Lease = @{ id = $script:CurrentJobId; lastVerified = [DateTimeOffset]::UtcNow }
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{} } } }
        Mock Invoke-OptimizerRequest { throw 'Simulated checkpoint transport timeout.' }
        { & $script:RealSave } | Should -Throw
        $script:StateWriteUncertain | Should -Be $true
        { & $script:RealSave } | Should -Throw '*unknown outcome*'
        Assert-MockCalled Invoke-OptimizerRequest -Times 1 -Exactly -ParameterFilter { $Method -eq 'Patch' -and $NoRetry }
    }

    It 'rejects string-valued ownership flags in a checkpoint' {
        $state = New-StopSnapshot
        $state.targets[0].stopAccepted = 'false'
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $state
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ optimizer_checkpoint = $script:EncodedCheckpoint } } } }
        { Read-OptimizerState } | Should -Throw '*booleans*'
    }

    It 'keeps already stopped apps off even if their original revisions are active' {
        Mock Invoke-ArmRequest {
            $app = New-TestApp
            $app.properties.runningStatus = 'Stopped'
            return @{ json = $app; status = 200 }
        }
        $script:State = New-StopSnapshot
        $script:State.phase = 'Stopped'
        $apps = @($script:State.targets | Where-Object kind -eq 'ContainerApp')
        @($apps | Where-Object shouldRestore).Count | Should -Be 0
        foreach ($entry in $apps) { Request-TargetAction -Entry $entry -RequestedAction START }
        Assert-MockCalled Invoke-ArmRequest -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }

    It 'refuses changed revision mode, routing and unrelated new active revisions' {
        $snapshot = New-StopSnapshot
        $entry = @($snapshot.targets | Where-Object kind -eq 'ContainerApp')[0]
        $entry.stopAccepted = $true
        Mock Invoke-ArmRequest {
            $app = New-TestApp
            $app.properties.configuration.activeRevisionsMode = 'Multiple'
            return @{ json = $app }
        }
        { Request-TargetAction -Entry $entry -RequestedAction START } | Should -Throw '*deployment changed*'
        Mock Invoke-ArmRequest {
            $app = New-TestApp
            $app.properties.configuration.ingress.traffic[0].weight = 90
            return @{ json = $app }
        }
        { Request-TargetAction -Entry $entry -RequestedAction START } | Should -Throw '*deployment changed*'
        Mock Invoke-ArmRequest { return @{ json = (New-TestApp) } }
        Mock Get-AppRevisions {
            return ,(@(New-TestRevisions) + @(@{ name = 'new-active-revision'; properties = @{ active = $true } }))
        }
        { Request-TargetAction -Entry $entry -RequestedAction START } | Should -Throw '*Unexpected active revision*'
        Assert-MockCalled Invoke-ArmRequest -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }

    It 'uses the stable ACA stop/start API and VM deallocate/start API versions' {
        Mock Invoke-OptimizerRequest { return @{ status = 200; json = @{} } }
        $appId = $script:Configuration.targets[0].id
        $null = & $script:RealArm -Path "$appId/stop" -Method Post
        $null = & $script:RealArm -Path "$appId/start" -Method Post
        Assert-MockCalled Invoke-OptimizerRequest -Times 2 -Exactly -ParameterFilter {
            $Method -eq 'Post' -and $Uri -match '/(stop|start)\?api-version=2026-07-01$'
        }
        $snapshot = New-StopSnapshot
        $vm = @($snapshot.targets | Where-Object id -like '*/runner-ado-weu-dev-001')[0]
        Request-TargetAction -Entry $vm -RequestedAction STOP
        Mock Get-VmPowerState { return 'PowerState/deallocated' }
        Request-TargetAction -Entry $vm -RequestedAction START
        Assert-MockCalled Invoke-ArmRequest -Times 2 -Exactly -ParameterFilter {
            $Method -eq 'Post' -and $ApiVersion -eq '2024-11-01' -and $Path -match '/(deallocate|start)$'
        }
    }

    It 'renews the job-bound lease before authenticated mutation requests' {
        Mock Update-StateLease {}
        Mock Get-ManagedIdentityToken { return 'unit-test-token' }
        Mock Invoke-WebRequest { return @{ StatusCode = 200; Content = '{}'; Headers = @{} } }
        $null = Invoke-OptimizerRequest -Uri 'https://management.azure.com/unit-test/action' -Method Post
        Assert-MockCalled Update-StateLease -Times 1 -Exactly -ParameterFilter { $Force }
        Assert-MockCalled Invoke-WebRequest -Times 1 -Exactly -ParameterFilter {
            $Headers.Authorization -eq 'Bearer unit-test-token' -and $Method -eq 'Post'
        }
    }

    It 'blocks transport mutations in Preview before token acquisition or HTTP' {
        $script:Mode = 'Preview'
        Mock Get-ManagedIdentityToken {}
        { Invoke-OptimizerRequest -Uri 'https://management.azure.com/unit-test/action' -Method Post } | Should -Throw '*Preview*'
        Assert-MockCalled Get-ManagedIdentityToken -Times 0 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }

    It 'blocks direct restoration requests after an unknown checkpoint write outcome' {
        $snapshot = New-StopSnapshot
        $entry = @($snapshot.targets | Where-Object shouldRestore)[0]
        $entry.stopAccepted = $true
        $script:StateWriteUncertain = $true
        { Request-TargetAction -Entry $entry -RequestedAction START } | Should -Throw '*unknown*'
        Assert-MockCalled Invoke-ArmRequest -Times 0 -Exactly -ParameterFilter { $Method -eq 'Post' }
    }
}

Describe 'Customer configuration and checkpoint binding' {
    BeforeEach {
        $script:Configuration = Copy-TestConfiguration
        $script:Fingerprint = Get-ConfigurationFingerprint $script:Configuration
        $script:State = New-IdleState $script:Fingerprint
        $script:Mode = 'Live'
        $script:CurrentJobId = [Guid]::NewGuid().ToString()
        $script:Lease = @{ id = $script:CurrentJobId; lastVerified = [DateTimeOffset]::UtcNow }
        $script:StateWriteUncertain = $false
        $script:StateContainerUri = 'https://management.azure.com/unit-test/container'
        Mock Invoke-WebRequest { throw 'No live HTTP is permitted in these tests.' }
    }

    It 'accepts a different customer tenant and subscription with one target' {
        $other = New-TestConfiguration -Customer Two -TargetCount 1
        { Assert-OptimizerConfiguration $other } | Should -Not -Throw
        $other.tenantId | Should -Not -Be $script:Configuration.tenantId
        $other.subscriptionId | Should -Not -Be $script:Configuration.subscriptionId
        $other.targets.Count | Should -Be 1
        (Get-ConfigurationFingerprint $other) | Should -Not -Be $script:Fingerprint
    }

    It 'accepts sixteen exact targets without assuming fixed app or VM counts' {
        $copy = Copy-TestConfiguration
        foreach ($index in 9..16) {
            $copy.targets += @{ kind = 'VirtualMachine'; id = "/subscriptions/$($copy.subscriptionId)/resourceGroups/$($copy.scope.resourceGroups[1])/providers/Microsoft.Compute/virtualMachines/worker-$index" }
        }
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Not -Throw
    }

    It 'rejects empty or oversized target allowlists' {
        $copy = Copy-TestConfiguration
        $copy.targets = @()
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*between 1 and 16*'
        $copy.targets = @(1..17 | ForEach-Object { $script:Configuration.targets[0] })
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*between 1 and 16*'
    }

    It 'rejects a target in another subscription even when the plan hash is valid' {
        $copy = Copy-TestConfiguration
        $copy.targets[0].id = $copy.targets[0].id.Replace($copy.subscriptionId, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*Unapproved resource ID*'
    }

    It 'rejects a guessed similar resource group rather than matching a factory prefix' {
        $copy = Copy-TestConfiguration
        $copy.targets[0].id = $copy.targets[0].id.Replace($copy.scope.resourceGroups[0], "$($copy.scope.resourceGroups[0])-other")
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*Unapproved or duplicate*'
    }

    It 'requires explicit common-group inclusion instead of broadening the scope' {
        $copy = Copy-TestConfiguration
        $copy.scope.resourceGroups = @($copy.scope.resourceGroups[0])
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*Unapproved or duplicate*'
        $copy.targets = @($copy.targets | Where-Object kind -eq 'ContainerApp')
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Not -Throw
    }

    It 'rejects unsupported providers and target-kind mismatches' {
        $copy = Copy-TestConfiguration
        $copy.targets[0].id = $copy.targets[0].id.Replace('Microsoft.App/containerApps', 'Microsoft.ContainerService/managedClusters')
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw
        $copy = Copy-TestConfiguration
        $copy.targets[0].kind = 'VirtualMachine'
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw
    }

    It 'rejects production and unresolved or wildcard resource scopes' {
        foreach ($environment in @('prod', 'production', 'DEV', '${environment}')) {
            $copy = Copy-TestConfiguration
            $copy.scope.environment = $environment
            Set-TestPlanHash $copy
            { Assert-OptimizerConfiguration $copy } | Should -Throw
        }
        foreach ($group in @('customer-one-*', '${resourceGroup}', 'your-resource-group')) {
            $copy = Copy-TestConfiguration
            $copy.scope.resourceGroups = @($group)
            Set-TestPlanHash $copy
            { Assert-OptimizerConfiguration $copy } | Should -Throw
        }
    }

    It 'accepts an explicit test environment and binds it differently from dev' {
        $copy = Copy-TestConfiguration
        $copy.scope.environment = 'test'
        $copy.scope.resourceGroups = @($copy.scope.resourceGroups | ForEach-Object { $_.Replace('-dev-', '-test-') })
        foreach ($target in $copy.targets) { $target.id = $target.id.Replace('-dev-', '-test-') }
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Not -Throw
        (Get-ConfigurationFingerprint $copy) | Should -Not -Be $script:Fingerprint
    }

    It 'rejects the optimizer hosting group in the target scope' {
        $copy = Copy-TestConfiguration
        $copy.scope.resourceGroups += $copy.resourceGroup
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*hosting group*'
    }

    It 'requires dedicated hosting names with the same twelve-hex deployment key' {
        foreach ($field in @('resourceGroup', 'automationAccount', 'stateStorageAccount')) {
            $copy = Copy-TestConfiguration
            $copy[$field] = $copy[$field].Replace('111122223333', '444455556666')
            Set-TestPlanHash $copy
            { Assert-OptimizerConfiguration $copy } | Should -Throw '*hosting*'
        }
        $copy = Copy-TestConfiguration
        $copy.resourceGroup = 'customer-one-esml-optimizer-rg'
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*dedicated*'
    }

    It 'rejects case-insensitive duplicate groups and targets' {
        $copy = Copy-TestConfiguration
        $copy.scope.resourceGroups += $copy.scope.resourceGroups[0].ToUpperInvariant()
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw
        $copy = Copy-TestConfiguration
        $copy.targets[1] = @{ kind = $copy.targets[0].kind; id = $copy.targets[0].id.Replace('/resourceGroups/', '/RESOURCEGROUPS/') }
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*duplicate*'
    }

    It 'validates deployment fields and exact scalar types' {
        $invalid = @(
            @{ field = 'tenantId'; value = 'not-a-guid' }
            @{ field = 'subscriptionId'; value = '00000000-0000-0000-0000-000000000000' }
            @{ field = 'schemaVersion'; value = '2' }
            @{ field = 'resourceGroup'; value = 'invalid/group' }
            @{ field = 'resourceGroup'; value = 'trailing-dot.' }
            @{ field = 'automationAccount'; value = 'bad' }
            @{ field = 'automationAccount'; value = ('a' * 51) }
            @{ field = 'stateStorageAccount'; value = 'UppercaseStorage' }
            @{ field = 'stateContainer'; value = 'other-container' }
            @{ field = 'stateTransport'; value = 'Blob' }
            @{ field = 'runtimeName'; value = 'PowerShell51' }
            @{ field = 'runbookName'; value = 'unreviewed-runbook' }
            @{ field = 'configurationVariable'; value = 'another-variable' }
            @{ field = 'location'; value = 'West Europe' }
            @{ field = 'operationTimeoutSeconds'; value = '1200' }
            @{ field = 'operationTimeoutSeconds'; value = 3601 }
            @{ field = 'timeZone'; value = 'Not/A_Time_Zone' }
            @{ field = 'firstStop'; value = '2026-10-10T03:00:00' }
            @{ field = 'firstStart'; value = '2026-02-30T08:00:00+02:00' }
            @{ field = 'stopTime'; value = '3:00' }
            @{ field = 'startTime'; value = '24:00' }
            @{ field = 'stopSchedule'; value = 'invalid/schedule' }
        )
        foreach ($case in $invalid) {
            $copy = Copy-TestConfiguration
            $copy[$case.field] = $case.value
            Set-TestPlanHash $copy
            { Assert-OptimizerConfiguration $copy } | Should -Throw -Because "$($case.field) must reject $($case.value)"
        }
    }

    It 'rejects missing or unexpected configuration fields' {
        $copy = Copy-TestConfiguration
        $copy.Remove('timeZone')
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw
        $copy = Copy-TestConfiguration
        $copy.unreviewedSetting = 'extra'
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Throw
    }

    It 'supports a Windows time-zone identifier as well as IANA' {
        $copy = Copy-TestConfiguration
        $copy.timeZone = 'W. Europe Standard Time'
        Set-TestPlanHash $copy
        { Assert-OptimizerConfiguration $copy } | Should -Not -Throw
    }

    It 'hashes recursive dictionary keys in ordinal order deterministically' {
        $one = @{ z = @([ordered]@{ z = 1; A = $true; b = 'value' }, @()); A = $null }
        $two = @{ A = $null; z = @([ordered]@{ b = 'value'; A = $true; z = 1 }, @()) }
        (ConvertTo-OptimizerCanonicalJson $one) | Should -BeExactly '{"A":null,"z":[{"A":true,"b":"value","z":1},[]]}'
        (Get-CostOptimizerPlanHash $one) | Should -BeExactly (Get-CostOptimizerPlanHash $two)
        (Get-CostOptimizerPlanHash $one) | Should -Match '^[0-9a-f]{64}$'
    }

    It 'preserves JSON array order and scalar types in the plan hash' {
        (Get-CostOptimizerPlanHash @{ values = @(1, 2) }) | Should -Not -Be (Get-CostOptimizerPlanHash @{ values = @(2, 1) })
        (Get-CostOptimizerPlanHash @{ value = 1 }) | Should -Not -Be (Get-CostOptimizerPlanHash @{ value = '1' })
        (Get-CostOptimizerPlanHash @{ value = $false }) | Should -Not -Be (Get-CostOptimizerPlanHash @{ value = 'false' })
        (Get-CostOptimizerPlanHash @{ value = $null }) | Should -Not -Be (Get-CostOptimizerPlanHash @{ value = '' })
        { Get-CostOptimizerPlanHash @{ value = [double]::NaN } } | Should -Throw
    }

    It 'does not collapse differently cased keys in a JSON object' {
        $value = [hashtable]::new([StringComparer]::Ordinal)
        $value.Add('a', 1)
        $value.Add('A', 2)
        (ConvertTo-OptimizerCanonicalJson $value) | Should -BeExactly '{"A":2,"a":1}'
        (Get-CostOptimizerPlanHash $value) | Should -Not -Be (Get-CostOptimizerPlanHash @{ a = 1 })
    }

    It 'ignores only the root planHash and detects changes to reviewed settings' {
        $copy = Copy-TestConfiguration
        $copy.planHash = '0' * 64
        (Get-CostOptimizerPlanHash $copy) | Should -BeExactly $script:Configuration.planHash
        { Assert-OptimizerConfiguration $copy } | Should -Throw '*plan hash*'
        $copy.firstStop = '2026-10-11T03:00:00+02:00'
        (Get-CostOptimizerPlanHash $copy) | Should -Not -Be $script:Configuration.planHash
        (Get-CostOptimizerPlanHash @{ nested = @{ planHash = 'one' } }) | Should -Not -Be (Get-CostOptimizerPlanHash @{ nested = @{ planHash = 'two' } })
    }

    It 'binds tenant, subscription, factory, environment, groups, targets and state hosting' {
        foreach ($field in @('tenantId', 'subscriptionId', 'resourceGroup', 'automationAccount', 'stateStorageAccount', 'stateContainer', 'stateTransport')) {
            $copy = Copy-TestConfiguration
            $copy[$field] += '-changed'
            (Get-ConfigurationFingerprint $copy) | Should -Not -Be $script:Fingerprint -Because "$field must bind the checkpoint"
        }
        foreach ($field in @('factoryKey', 'environment')) {
            $copy = Copy-TestConfiguration
            $copy.scope[$field] += '-changed'
            (Get-ConfigurationFingerprint $copy) | Should -Not -Be $script:Fingerprint
        }
        $copy = Copy-TestConfiguration
        $copy.scope.resourceGroups += 'extra-exact-group'
        (Get-ConfigurationFingerprint $copy) | Should -Not -Be $script:Fingerprint
        $copy = Copy-TestConfiguration
        $copy.targets = @($copy.targets[0])
        (Get-ConfigurationFingerprint $copy) | Should -Not -Be $script:Fingerprint
    }

    It 'does not invalidate restoration ownership when only scheduling or array order changes' {
        $copy = Copy-TestConfiguration
        $copy.firstStop = '2026-10-11T03:00:00+02:00'
        $copy.stopSchedule = 'NEW-STOP'
        $copy.stopTime = '04:00'
        $copy.timeZone = 'UTC'
        [Array]::Reverse($copy.targets)
        [Array]::Reverse($copy.scope.resourceGroups)
        (Get-ConfigurationFingerprint $copy) | Should -BeExactly $script:Fingerprint
        (Get-CostOptimizerPlanHash $copy) | Should -Not -Be $script:Configuration.planHash
    }

    It 'fails closed when a paused checkpoint has a different customer binding' {
        $state = @{
            schemaVersion = 1; fingerprint = '0' * 64; phase = 'Stopped'; targets = @()
        }
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $state
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ optimizer_checkpoint = $script:EncodedCheckpoint } } } }
        { Read-OptimizerState } | Should -Throw '*outstanding STOP*'
    }

    It 'rebinds an idle checkpoint without writing or restoring old targets' {
        $old = New-IdleState ('0' * 64)
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $old
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ optimizer_checkpoint = $script:EncodedCheckpoint } } } }
        $read = Read-OptimizerState
        $read.exists | Should -Be $true
        $read.data.fingerprint | Should -Be $script:Fingerprint
        $read.data.phase | Should -Be 'Idle'
        $read.data.targets.Count | Should -Be 0
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }

    It 'rebinds only a fully restored Started checkpoint to another customer' {
        $old = New-IdleState ('0' * 64)
        $old.phase = 'Started'
        $old.targets = @(@{
            id = (New-TestConfiguration -Customer Two -TargetCount 1).targets[0].id
            kind = 'ContainerApp'; shouldRestore = $true; stopAttempted = $true; stopAccepted = $true
            status = 'Started'; originalRunningStatus = 'Running'; revisions = @(@{ name = 'old-revision' })
        })
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $old
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ optimizer_checkpoint = $script:EncodedCheckpoint } } } }
        (Read-OptimizerState).data.phase | Should -Be 'Idle'
        $old.targets[0].status = 'StopFailed'
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $old
        { Read-OptimizerState } | Should -Throw '*outstanding*'
    }

    It 'rejects an unresolved STOP attempt even if the checkpoint claims Started' {
        $old = New-IdleState ('0' * 64)
        $old.phase = 'Started'
        $old.targets = @(@{
            id = $script:Configuration.targets[3].id
            kind = 'VirtualMachine'; shouldRestore = $true; stopAttempted = $true; stopAccepted = $false
            status = 'Skipped'; originalPowerState = 'PowerState/running'
        })
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $old
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ optimizer_checkpoint = $script:EncodedCheckpoint } } } }
        { Read-OptimizerState } | Should -Throw '*outstanding*'
    }

    It 'does not reset a terminal checkpoint whose restoration statuses contradict its ownership flags' {
        $old = New-IdleState ('0' * 64)
        $old.phase = 'Started'
        $old.targets = @(@{
            id = $script:Configuration.targets[3].id
            kind = 'VirtualMachine'; shouldRestore = $true; stopAttempted = $false; stopAccepted = $false
            status = 'Stopped'; originalPowerState = 'PowerState/running'
        })
        $script:EncodedCheckpoint = ConvertTo-CheckpointMetadata $old
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ optimizer_checkpoint = $script:EncodedCheckpoint } } } }
        { Read-OptimizerState } | Should -Throw '*outstanding*'
    }

    It 'fails before target mutations when the compressed checkpoint exceeds the metadata cap' {
        $script:OversizedSnapshot = New-IdleState $script:Fingerprint
        $script:OversizedSnapshot.phase = 'Stopping'
        $script:OversizedSnapshot.padding = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(12000))
        Mock New-StopSnapshot { return $script:OversizedSnapshot }
        Mock Save-OptimizerState { & $script:RealSave }
        Mock Request-TargetAction {}
        { Invoke-StatefulAction STOP } | Should -Throw '*safe container metadata limit*'
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
        $script:StateWriteUncertain | Should -Be $false
    }

    It 'does not persist a highly compressible checkpoint that its bounded reader cannot decode' {
        $script:OversizedSnapshot = New-IdleState $script:Fingerprint
        $script:OversizedSnapshot.padding = 'x' * 262144
        Mock New-StopSnapshot { return $script:OversizedSnapshot }
        Mock Save-OptimizerState { & $script:RealSave }
        Mock Request-TargetAction {}
        { Invoke-StatefulAction STOP } | Should -Throw '*decompression limit*'
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
        $script:StateWriteUncertain | Should -Be $false
    }

    It 'fails before target mutations when unrelated metadata exhausts the total cap' {
        Mock New-StopSnapshot { return (New-IdleState $script:Fingerprint) }
        Mock Get-StateContainer { return @{ properties = @{ metadata = @{ customer_metadata = 'x' * 7800 } } } }
        Mock Save-OptimizerState { & $script:RealSave }
        Mock Request-TargetAction {}
        { Invoke-StatefulAction STOP } | Should -Throw '*Total state-container metadata*'
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
        $script:StateWriteUncertain | Should -Be $false
    }

    It 'runs Live VERIFY using hosted job identity without issuing target actions' {
        $script:HostedJobId = [Guid]::NewGuid()
        Mock Get-AutomationVariable { return ($script:Configuration | ConvertTo-Json -Depth 25 -Compress) }
        Mock Get-Variable { return $script:HostedJobId } -ParameterFilter { $Name -eq 'AutomationPSPrivateMetadataJobId' }
        Mock Enter-StateLease {
            $script:Lease = @{ id = $script:CurrentJobId; lastVerified = [DateTimeOffset]::UtcNow }
            $script:State = New-IdleState $script:Fingerprint
        }
        Mock Save-OptimizerState {}
        Mock Get-OptimizerJobHistory { return ,@() }
        Mock Exit-StateLease { $script:Lease = $null }
        Mock Request-TargetAction {}
        $result = Invoke-OptimizerMain -RequestedAction VERIFY -RequestedMode Live
        $result.action | Should -Be 'VERIFY'
        $script:CurrentJobId | Should -Be $script:HostedJobId.ToString()
        Assert-MockCalled Save-OptimizerState -Times 1 -Exactly
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        Assert-MockCalled Exit-StateLease -Times 1 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }

    It 'retains the infinite mutex when VERIFY checkpoint persistence is uncertain' {
        Mock Get-AutomationVariable { return ($script:Configuration | ConvertTo-Json -Depth 25 -Compress) }
        Mock Get-Variable { return [Guid]::NewGuid() } -ParameterFilter { $Name -eq 'AutomationPSPrivateMetadataJobId' }
        Mock Enter-StateLease {
            $script:Lease = @{ id = $script:CurrentJobId; lastVerified = [DateTimeOffset]::UtcNow }
            $script:State = New-IdleState $script:Fingerprint
        }
        Mock Save-OptimizerState {
            $script:StateWriteUncertain = $true
            throw 'Unknown persistence outcome.'
        }
        Mock Exit-StateLease {}
        Mock Request-TargetAction {}
        { Invoke-OptimizerMain -RequestedAction VERIFY -RequestedMode Live } | Should -Throw '*Unknown persistence*'
        Assert-MockCalled Exit-StateLease -Times 0 -Exactly
        Assert-MockCalled Request-TargetAction -Times 0 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }

    It 'fails closed on an empty hosted job identity before acquiring any lease' {
        Mock Get-AutomationVariable { return ($script:Configuration | ConvertTo-Json -Depth 25 -Compress) }
        Mock Get-Variable { return [Guid]::Empty } -ParameterFilter { $Name -eq 'AutomationPSPrivateMetadataJobId' }
        Mock Enter-StateLease {}
        { Invoke-OptimizerMain -RequestedAction VERIFY -RequestedMode Live } | Should -Throw '*job identity*'
        Assert-MockCalled Enter-StateLease -Times 0 -Exactly
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }
}
