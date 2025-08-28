// ================================================================
// ACR RBAC VERIFICATION MODULE
// This module verifies that the required ACR pull permissions 
// are properly assigned before Container Apps deployment
// ================================================================

targetScope = 'resourceGroup'

@description('Name of the Container Registry')
param containerRegistryName string

@description('Principal ID of the managed identity that needs ACR access')
param principalId string

@description('Role definition ID for ACR pull access (default: AcrPull)')
param roleDefinitionId string = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

@description('Enable verification output for debugging')
param enableVerboseOutput bool = false

// ============================================================================
// EXISTING RESOURCES
// ============================================================================

resource existingACR 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

// ============================================================================
// RBAC VERIFICATION
// ============================================================================

// Create a deployment script to verify RBAC assignment
resource rbacVerificationScript 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'verify-acr-rbac-${substring(uniqueString(containerRegistryName, principalId), 0, 8)}'
  location: resourceGroup().location
  kind: 'AzurePowerShell'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    azPowerShellVersion: '11.0'
    timeout: 'PT10M'
    retentionInterval: 'PT1H'
    arguments: '-ContainerRegistryName "${containerRegistryName}" -PrincipalId "${principalId}" -RoleDefinitionId "${roleDefinitionId}" -ResourceGroupName "${resourceGroup().name}" -SubscriptionId "${subscription().subscriptionId}" -ACRResourceId "${existingACR.id}"'
    scriptContent: '''
      param(
        [string]$ContainerRegistryName,
        [string]$PrincipalId,
        [string]$RoleDefinitionId,
        [string]$ResourceGroupName,
        [string]$SubscriptionId,
        [string]$ACRResourceId
      )
      
      Write-Output "Starting ACR RBAC verification for Container Apps deployment..."
      Write-Output "Container Registry: $ContainerRegistryName"
      Write-Output "Principal ID: $PrincipalId"
      Write-Output "Role Definition ID: $RoleDefinitionId"
      Write-Output "ACR Resource ID: $ACRResourceId"
      
      # Set context
      Set-AzContext -SubscriptionId $SubscriptionId
      
      # Check for existing role assignment
      $maxRetries = 30
      $retryCount = 0
      $roleAssignmentFound = $false
      
      do {
        Write-Output "Checking for role assignment (attempt $($retryCount + 1)/$maxRetries)..."
        
        $roleAssignments = Get-AzRoleAssignment -Scope $ACRResourceId -ObjectId $PrincipalId -RoleDefinitionId $RoleDefinitionId -ErrorAction SilentlyContinue
        
        if ($roleAssignments -and $roleAssignments.Count -gt 0) {
          $roleAssignmentFound = $true
          Write-Output "✅ ACR pull role assignment found!"
          Write-Output "Role Assignment Details:"
          foreach ($assignment in $roleAssignments) {
            Write-Output "  - Assignment ID: $($assignment.RoleAssignmentId)"
            Write-Output "  - Role Name: $($assignment.RoleDefinitionName)"
            Write-Output "  - Principal Type: $($assignment.ObjectType)"
          }
          break
        }
        
        if ($retryCount -lt $maxRetries - 1) {
          Write-Output "Role assignment not yet available, waiting 10 seconds..."
          Start-Sleep -Seconds 10
        }
        
        $retryCount++
      } while ($retryCount -lt $maxRetries)
      
      if (-not $roleAssignmentFound) {
        Write-Error "❌ ACR pull role assignment not found after $maxRetries attempts!"
        Write-Output "This may cause Container Apps deployment to fail with ACR access denied errors."
        Write-Output "Expected role: AcrPull (7f951dda-4ed3-4680-a7ca-43fe172d538d)"
        Write-Output "Principal ID: $PrincipalId"
        Write-Output "ACR Scope: $ACRResourceId"
        
        # List all role assignments for debugging
        Write-Output "All role assignments for this principal:"
        $allAssignments = Get-AzRoleAssignment -ObjectId $PrincipalId -ErrorAction SilentlyContinue
        if ($allAssignments) {
          foreach ($assignment in $allAssignments) {
            Write-Output "  - Scope: $($assignment.Scope)"
            Write-Output "    Role: $($assignment.RoleDefinitionName)"
          }
        } else {
          Write-Output "  No role assignments found for this principal"
        }
        
        throw "ACR RBAC verification failed - Container Apps may not be able to pull images"
      }
      
      Write-Output "🎉 ACR RBAC verification completed successfully!"
      Write-Output "Container Apps should now be able to pull images from ACR: $ContainerRegistryName"
      
      # Output for Bicep
      $DeploymentScriptOutputs = @{}
      $DeploymentScriptOutputs['rbacVerified'] = $roleAssignmentFound
      $DeploymentScriptOutputs['acrResourceId'] = $ACRResourceId
      $DeploymentScriptOutputs['verificationTimestamp'] = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss UTC')
    '''
    cleanupPreference: 'OnSuccess'
  }
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Indicates whether ACR RBAC verification was successful')
output rbacVerifiedAndExists bool = rbacVerificationScript.properties.outputs.rbacVerified

@description('ACR Resource ID that was verified')
output acrResourceId string = rbacVerificationScript.properties.outputs.acrResourceId

@description('Timestamp when verification was completed')
output verificationTimestamp string = rbacVerificationScript.properties.outputs.verificationTimestamp

@description('Verification details for troubleshooting')
output verificationSummary object = {
  containerRegistryName: containerRegistryName
  principalId: principalId
  roleDefinitionId: roleDefinitionId
  rbacVerifiedAndExists: rbacVerificationScript.properties.outputs.rbacVerified
  timestamp: rbacVerificationScript.properties.outputs.verificationTimestamp
}
