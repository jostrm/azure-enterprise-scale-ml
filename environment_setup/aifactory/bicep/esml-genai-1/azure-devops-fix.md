# Azure DevOps Pipeline Configuration to Fix "Response Already Consumed" Error

## The error is likely still occurring due to one of these reasons:

### 1. Azure DevOps Task Timeout Configuration
The default timeout for Azure Resource Manager deployment tasks is often too short for large Bicep templates.

**Solution: Update your Azure DevOps pipeline YAML:**

```yaml
- task: AzureResourceManagerTemplateDeployment@3
  displayName: 'Deploy Bicep Template'
  inputs:
    azureResourceManagerConnection: '$(serviceConnection)'
    subscriptionId: '$(subscriptionId)'
    resourceGroupName: '$(resourceGroupName)'
    location: '$(location)'
    templateLocation: 'Linked artifact'
    csmFile: '$(Pipeline.Workspace)/bicep/32-main.bicep'
    csmParametersFile: '$(Pipeline.Workspace)/bicep/32-main.parameters.json'
    deploymentMode: 'Incremental'
    deploymentName: 'bicep-deployment-$(Build.BuildId)'
    timeoutInMinutes: 120  # CRITICAL: Increase from default 60 to 120 minutes
  timeoutInMinutes: 130    # CRITICAL: Pipeline task timeout (slightly higher than deployment)
  retryCountOnTaskFailure: 2  # Retry on transient failures
  continueOnError: false
```

### 2. Template Size and Complexity Issues
Your template is very large (3500+ lines) which can cause ARM API limits.

**Solutions:**

#### Option A: Split Template into Multiple Deployments
```yaml
# Deploy infrastructure first
- task: AzureResourceManagerTemplateDeployment@3
  displayName: 'Deploy Core Infrastructure'
  inputs:
    csmFile: '$(Pipeline.Workspace)/bicep/01-infrastructure.bicep'
    timeoutInMinutes: 60

# Deploy services second  
- task: AzureResourceManagerTemplateDeployment@3
  displayName: 'Deploy AI Services'
  inputs:
    csmFile: '$(Pipeline.Workspace)/bicep/02-ai-services.bicep'
    timeoutInMinutes: 60
```

#### Option B: Use DeploymentStack (Preview)
```yaml
- task: AzureCLI@2
  displayName: 'Deploy with Deployment Stack'
  inputs:
    azureSubscription: '$(serviceConnection)'
    scriptType: 'bash'
    scriptLocation: 'inlineScript'
    inlineScript: |
      az stack group create \
        --name "mystack" \
        --resource-group "$(resourceGroupName)" \
        --template-file "32-main.bicep" \
        --parameters "@32-main.parameters.json" \
        --deny-settings-mode "none" \
        --timeout 7200  # 2 hours
```

### 3. Conditional Module Loading Issues
The error might still be caused by conditional module outputs being accessed.

**Check your parameter files for these settings:**
```json
{
  "parameters": {
    "enableAIServices": { "value": true },
    "enableAIFoundryHub": { "value": true },
    "enableAISearch": { "value": true },
    "serviceSettingDeployAzureOpenAI": { "value": true }
  }
}
```

### 4. Azure Resource Provider Registration
Ensure all required resource providers are registered:

```yaml
- task: AzureCLI@2
  displayName: 'Register Resource Providers'
  inputs:
    azureSubscription: '$(serviceConnection)'
    scriptType: 'bash'
    scriptLocation: 'inlineScript'
    inlineScript: |
      az provider register --namespace Microsoft.MachineLearningServices
      az provider register --namespace Microsoft.CognitiveServices
      az provider register --namespace Microsoft.Search
      az provider register --namespace Microsoft.ContainerRegistry
      az provider register --namespace Microsoft.KeyVault
      az provider register --namespace Microsoft.Storage
```

### 5. Resource Quotas and Limits
Check if you're hitting Azure subscription limits:

```yaml
- task: AzureCLI@2
  displayName: 'Check Quotas'
  inputs:
    azureSubscription: '$(serviceConnection)'
    scriptType: 'bash'
    scriptLocation: 'inlineScript'
    inlineScript: |
      az vm list-usage --location "$(location)" --out table
      az cognitiveservices account list-usage --resource-group "$(resourceGroupName)" --out table
```

## Recommended Immediate Fix:

1. **Update your Azure DevOps pipeline with the timeout settings above**
2. **Add retry logic**
3. **Consider splitting the deployment into smaller chunks**

The "content for this response was already consumed" error at exactly 25 seconds suggests a timeout rather than a Bicep compilation issue.
