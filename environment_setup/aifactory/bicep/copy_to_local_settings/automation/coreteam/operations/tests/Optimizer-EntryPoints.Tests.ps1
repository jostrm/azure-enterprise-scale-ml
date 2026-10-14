#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.7.1' }
BeforeAll {
    $script:Operations = Split-Path $PSScriptRoot -Parent
    . "$script:Operations\Tenant-Cost-Optimizer.ps1"
    . "$script:Operations\Optimizer-Configuration.ps1"
    . "$script:Operations\Azure-Control.ps1"
    function az {}
    function New-EntryPointVariables {
        return @{
            dev = @{
                tenantId = '11111111-1111-4111-8111-111111111111'
                dev_sub_id = '22222222-2222-4222-8222-222222222222'
                admin_location = 'westeurope'
                admin_locationSuffix = 'weu'
                admin_aifactoryPrefixRG = 'customer-plan-'
                admin_aifactorySuffixRG = '-002'
                projectPrefix = 'esml-'
                projectSuffix = '-rg'
                vnetResourceGroupBase = 'esml-common'
                commonResourceGroup_param = ''
                project_number_000 = '009'
                unrelatedSecretSetting = 'must-not-export-this-value'
            }
        }
    }
}

Describe 'Read-only plan and deployment approval entry points' {
    BeforeEach {
        $script:VariablesFile = Join-Path $TestDrive 'variables.json'
        New-EntryPointVariables | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $script:VariablesFile
        $script:OutputFile = Join-Path $TestDrive "$([Guid]::NewGuid()).local.json"
        Mock az {
            $global:LASTEXITCODE = 0
            if ($args[0] -eq 'account' -and $args[1] -eq 'show') {
                return '{"tenantId":"11111111-1111-4111-8111-111111111111","id":"22222222-2222-4222-8222-222222222222"}'
            }
            return 'mock-token'
        }
        Mock Invoke-WebRequest {
            $id = '/subscriptions/22222222-2222-4222-8222-222222222222/resourceGroups/customer-plan-esml-project009-weu-dev-002-rg/providers/Microsoft.App/containerApps/customer-salted-chat'
            $body = @{ value = @(@{ id = $id; type = 'Microsoft.App/containerApps' }) } | ConvertTo-Json -Depth 8
            return @{ StatusCode = 200; Content = $body; Headers = @{} }
        }
    }

    It 'exports a valid customer-neutral reviewed plan without any cloud writes or unrelated variables' {
        $null = & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile
        $plan = Get-Content -LiteralPath $script:OutputFile -Raw | ConvertFrom-Json -AsHashtable -DateKind String
        { Assert-OptimizerConfiguration $plan } | Should -Not -Throw
        $plan.planHash | Should -Be (Get-CostOptimizerPlanHash $plan)
        $plan.targets.Count | Should -Be 1
        $plan.targets[0].id | Should -Match 'customer-salted-chat$'
        Get-Content -LiteralPath $script:OutputFile -Raw | Should -Not -Match 'must-not-export'
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly -ParameterFilter { $Method -ne 'Get' }
    }

    It 'rejects an incorrect approval hash before any deployment request' {
        $null = & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile
        { & "$script:Operations\Deploy-TenantCostOptimizer.ps1" -ConfigurationPath $script:OutputFile `
            -ApprovedPlanHash ('0' * 64) } | Should -Throw '*Approval*'
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly -ParameterFilter { $Method -ne 'Get' }
    }

    It 'submits the selected STOP and START rather than resetting them to runtime STATUS defaults' {
        $null = & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile
        foreach ($action in @('STOP', 'START')) {
            $null = & "$script:Operations\Invoke-TenantCostOptimizer.ps1" $action `
                -ConfigurationPath $script:OutputFile -NoWait
            Assert-MockCalled Invoke-WebRequest -Times 1 -Exactly -ParameterFilter {
                $Method -eq 'Put' -and
                ([Text.Encoding]::UTF8.GetString($Body) | ConvertFrom-Json).properties.parameters.Action -eq $action -and
                ([Text.Encoding]::UTF8.GetString($Body) | ConvertFrom-Json).properties.parameters.Mode -eq 'Live'
            }
        }
    }

    It 'submits an explicit STOP preview without upgrading it to Live' {
        $null = & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile
        $null = & "$script:Operations\Invoke-TenantCostOptimizer.ps1" STOP `
            -ConfigurationPath $script:OutputFile -Preview -NoWait
        Assert-MockCalled Invoke-WebRequest -Times 1 -Exactly -ParameterFilter {
            $Method -eq 'Put' -and
            ([Text.Encoding]::UTF8.GetString($Body) | ConvertFrom-Json).properties.parameters.Action -eq 'STOP' -and
            ([Text.Encoding]::UTF8.GetString($Body) | ConvertFrom-Json).properties.parameters.Mode -eq 'Preview'
        }
    }

    It 'rejects a changed target list and plan hash before manual job submission' {
        $null = & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile
        $plan = Get-Content -LiteralPath $script:OutputFile -Raw | ConvertFrom-Json -AsHashtable -DateKind String
        $plan.targets[0].id = $plan.targets[0].id.Replace('customer-salted-chat', 'unreviewed-app')
        $plan | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $script:OutputFile
        { & "$script:Operations\Invoke-TenantCostOptimizer.ps1" STOP -ConfigurationPath $script:OutputFile } | Should -Throw
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly -ParameterFilter { $Method -ne 'Get' }
    }

    It 'does not overwrite an existing reviewed plan' {
        $null = & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile
        $before = (Get-FileHash $script:OutputFile).Hash
        { & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Kinds ContainerApp -OutputPath $script:OutputFile } | Should -Throw '*overwrite*'
        (Get-FileHash $script:OutputFile).Hash | Should -Be $before
    }

    It 'rejects production before authentication or inventory discovery' {
        { & "$script:Operations\New-CostOptimizerPlan.ps1" -VariablesPath $script:VariablesFile `
            -Environment prod -Kinds ContainerApp -OutputPath $script:OutputFile } | Should -Throw '*Production*'
        Assert-MockCalled Invoke-WebRequest -Times 0 -Exactly
    }
}
