#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.7.1' }
BeforeAll {
    . "$PSScriptRoot\..\Optimizer-Configuration.ps1"
    function New-TestVariables {
        return @{
            dev = @{
                tenantId = '11111111-1111-4111-8111-111111111111'
                dev_sub_id = '22222222-2222-4222-8222-222222222222'
                admin_location = 'westeurope'
                admin_locationSuffix = 'weu'
                admin_aifactoryPrefixRG = 'customer-one-'
                admin_aifactorySuffixRG = '-001'
                projectPrefix = 'esml-'
                projectSuffix = '-rg'
                vnetResourceGroupBase = 'esml-common'
                commonResourceGroup_param = ''
                project_number_000 = '007'
            }
            stage_prod = @{
                tenantId = '33333333-3333-4333-8333-333333333333'
                test_sub_id = '44444444-4444-4444-8444-444444444444'
                prod_sub_id = '55555555-5555-4555-8555-555555555555'
                admin_location = 'swedencentral'
                admin_locationSuffix = 'sdc'
                commonResourceGroup_param = ''
            }
        }
    }
    function New-TestResource {
        param([hashtable]$Scope, [string]$Group, [string]$Type, [string]$Name)
        return @{
            id = "/subscriptions/$($Scope.subscriptionId)/resourceGroups/$Group/providers/$Type/$Name"
            type = $Type
        }
    }
}

Describe 'Customer Factory variables resolution' {
    It 'derives dev project/common groups from the existing Factory naming keys' {
        $scope = Resolve-CostOptimizerScope -Variables (New-TestVariables) -IncludeCommonVms
        $scope.projectResourceGroups | Should -Contain 'customer-one-esml-project007-weu-dev-001-rg'
        $scope.commonResourceGroup | Should -Be 'customer-one-esml-common-weu-dev-001'
        $scope.subscriptionId | Should -Be '22222222-2222-4222-8222-222222222222'
        $scope.resourceGroups.Count | Should -Be 2
    }

    It 'keeps common VMs outside the scope unless explicitly selected' {
        $scope = Resolve-CostOptimizerScope -Variables (New-TestVariables)
        $scope.resourceGroups.Count | Should -Be 1
        $scope.resourceGroups | Should -Not -Contain $scope.commonResourceGroup
    }

    It 'maps stage to test and uses the exact stage_prod identity with overlay naming' {
        $scope = Resolve-CostOptimizerScope -Variables (New-TestVariables) -Environment stage
        $scope.environment | Should -Be 'test'
        $scope.tenantId | Should -Be '33333333-3333-4333-8333-333333333333'
        $scope.subscriptionId | Should -Be '44444444-4444-4444-8444-444444444444'
        $scope.projectResourceGroups | Should -Contain 'customer-one-esml-project007-sdc-test-001-rg'
    }

    It 'does not inherit dev tenant/subscription when selected identity is incomplete' {
        $variables = New-TestVariables
        $variables.stage_prod.Remove('tenantId')
        { Resolve-CostOptimizerScope -Variables $variables -Environment test } | Should -Throw '*tenantId*'
    }

    It 'rejects production, unresolved GUIDs, project zero, All and duplicates' {
        { Resolve-CostOptimizerScope -Variables (New-TestVariables) -Environment prod } | Should -Throw '*Production*'
        $variables = New-TestVariables
        $variables.dev.tenantId = '<todo>_TenantId'
        { Resolve-CostOptimizerScope -Variables $variables } | Should -Throw
        foreach ($numbers in @(@('000'), @('All'), @('007', '007'))) {
            { Resolve-CostOptimizerScope -Variables (New-TestVariables) -ProjectNumbers $numbers } | Should -Throw
        }
    }

    It 'supports BYO common RG and distinct explicit project scopes' {
        $variables = New-TestVariables
        $variables.dev.commonResourceGroup_param = 'customer-one-byo-common'
        $scope = Resolve-CostOptimizerScope -Variables $variables -ProjectNumbers '007','008' -IncludeCommonVms
        $scope.commonResourceGroup | Should -Be 'customer-one-byo-common'
        $scope.resourceGroups.Count | Should -Be 3
        $scope.projectResourceGroups | Should -Contain 'customer-one-esml-project008-weu-dev-001-rg'
    }

    It 'uses different customer and environment boundaries without hardcoded tenant names' {
        $first = Resolve-CostOptimizerScope -Variables (New-TestVariables)
        $variables = New-TestVariables
        $variables.dev.admin_aifactoryPrefixRG = 'customer-two-'
        $variables.dev.tenantId = '66666666-6666-4666-8666-666666666666'
        $variables.dev.dev_sub_id = '77777777-7777-4777-8777-777777777777'
        $second = Resolve-CostOptimizerScope -Variables $variables
        $stage = Resolve-CostOptimizerScope -Variables (New-TestVariables) -Environment test
        $first.factoryKey | Should -Not -Be $second.factoryKey
        $first.factoryKey | Should -Not -Be $stage.factoryKey
        $second.projectResourceGroups | Should -Contain 'customer-two-esml-project007-weu-dev-001-rg'
    }
}

Describe 'Bounded inventory to immutable targets' {
    BeforeEach {
        $scope = Resolve-CostOptimizerScope -Variables (New-TestVariables) -IncludeCommonVms
        $project = $scope.projectResourceGroups[0]
        $inventory = @(
            (New-TestResource $scope $project 'Microsoft.App/containerApps' 'app-one'),
            (New-TestResource $scope $project 'Microsoft.ContainerService/managedClusters' 'aks-one'),
            (New-TestResource $scope $scope.commonResourceGroup 'Microsoft.Compute/virtualMachines' 'runner-one'),
            (New-TestResource $scope $scope.commonResourceGroup 'Microsoft.App/containerApps' 'shared-app')
        )
    }

    It 'includes only supported project resources and opted-in common VMs, never AKS' {
        $targets = Select-CostOptimizerTargets $scope $inventory -Kinds ContainerApp,VirtualMachine
        $targets.Count | Should -Be 2
        $targets.id -join '|' | Should -Not -Match 'aks-one|shared-app'
    }

    It 'narrows to exact reviewed IDs and fails on missing targets' {
        $targets = Select-CostOptimizerTargets $scope $inventory -Kinds ContainerApp,VirtualMachine -TargetResourceIds $inventory[0].id
        $targets.Count | Should -Be 1
        { Select-CostOptimizerTargets $scope $inventory -Kinds ContainerApp -TargetResourceIds '/not/discovered' } | Should -Throw '*not discovered*'
    }

    It 'rejects leaked cross-subscription/group IDs, duplicate inventory and zero targets' {
        $outside = New-TestResource $scope 'customer-other-rg' 'Microsoft.App/containerApps' 'app'
        { Select-CostOptimizerTargets $scope @($outside) -Kinds ContainerApp } | Should -Throw '*outside*'
        $outside = @{} + $inventory[0]
        $outside.id = $outside.id.Replace($scope.subscriptionId, '88888888-8888-4888-8888-888888888888')
        { Select-CostOptimizerTargets $scope @($outside) -Kinds ContainerApp } | Should -Throw '*outside*'
        { Select-CostOptimizerTargets $scope @($inventory[0], $inventory[0]) -Kinds ContainerApp } | Should -Throw '*Duplicate*'
        { Select-CostOptimizerTargets $scope @() -Kinds ContainerApp } | Should -Throw '*1 to 16*'
    }

    It 'limits checkpoint scope rather than generating a plan too large to restore safely' {
        $many = @(1..17 | ForEach-Object { New-TestResource $scope $project 'Microsoft.App/containerApps' "app-$_" })
        { Select-CostOptimizerTargets $scope $many -Kinds ContainerApp } | Should -Throw '*1 to 16*'
    }
}

Describe 'Daylight-saving-aware local schedules' {
    It 'uses CEST and CET offsets without changing the local trigger hours' {
        $summer = Get-CostOptimizerScheduleTimes -FirstStopDate '2027-06-01' -Now ([DateTimeOffset]'2027-05-31T00:00:00Z')
        $winter = Get-CostOptimizerScheduleTimes -FirstStopDate '2027-01-01' -Now ([DateTimeOffset]'2026-12-31T00:00:00Z')
        $summer.firstStop | Should -Match 'T03:00:00.*\+02:00$'
        $winter.firstStop | Should -Match 'T03:00:00.*\+01:00$'
    }

    It 'places START the following day for an overnight 22:00/08:00 window' {
        $times = Get-CostOptimizerScheduleTimes -StopTime '22:00' -StartTime '08:00' -FirstStopDate '2027-01-01' `
            -Now ([DateTimeOffset]'2026-12-31T00:00:00Z')
        $times.firstStart | Should -Match '^2027-01-02T08:00'
    }

    It 'rejects past, malformed, equal and ambiguous initial trigger times' {
        { Get-CostOptimizerScheduleTimes -FirstStopDate '2026-01-01' -Now ([DateTimeOffset]'2026-01-02T00:00:00Z') } | Should -Throw
        { Get-CostOptimizerScheduleTimes -StopTime '25:00' } | Should -Throw
        { Get-CostOptimizerScheduleTimes -StopTime '03:00' -StartTime '03:00' } | Should -Throw
        { Get-CostOptimizerScheduleTimes -FirstStopDate '2026-10-25' -StopTime '02:30' `
            -Now ([DateTimeOffset]'2026-10-24T00:00:00Z') } | Should -Throw '*daylight-saving*'
    }
}
