#!/bin/bash

echo "=== Purge Soft-Deleted Resources After 5 Minutes ==="
echo "This task purges soft-deleted resources from tasks 71-72 if they successfully deleted resources"

az account set --subscription "$(dev_test_prod_sub_id)"

# Check which tasks performed deletions
task_71_deleted="$(71_deleted)"
task_72_deleted="$(72_deleted)"

echo "Task 71 deleted resources: $task_71_deleted"
echo "Task 72 deleted resources: $task_72_deleted"

# Wait 5 minutes before attempting purge (soft-delete retention period)
echo "Waiting 5 minutes before attempting to purge soft-deleted resources..."
sleep 300

# Input parameters - replicating the same logic from previous tasks
commonRGNamePrefix="$(admin_aifactoryPrefixRG)"
projectNumber="$(project_number_000)"
projectName="prj${projectNumber}"
locationSuffix="$(admin_locationSuffix)"
envName="$(dev_test_prod)"
aifactorySuffixRG="$(admin_aifactorySuffixRG)"
location="$(admin_location)"

echo "Location: $location"
echo "Project: $projectName"

# Function to purge soft-deleted Cognitive Services accounts
purge_cognitive_services() {
  echo "=== Checking for soft-deleted Cognitive Services accounts to purge ==="
  
  # List soft-deleted accounts in the location
  soft_deleted_accounts=$(az cognitiveservices account list-deleted \
    --location "$location" \
    --query "[].{name:name, location:location, deletionDate:deletionDate}" \
    --output json 2>/dev/null || echo "[]")
  
  if [ "$soft_deleted_accounts" != "[]" ] && [ -n "$soft_deleted_accounts" ]; then
    echo "Found soft-deleted Cognitive Services accounts:"
    echo "$soft_deleted_accounts"
    
    # Extract account names and attempt to purge them
    account_names=$(echo "$soft_deleted_accounts" | jq -r '.[].name' 2>/dev/null || echo "")
    
    if [ -n "$account_names" ]; then
      while IFS= read -r account_name; do
        if [ -n "$account_name" ]; then
          echo "Attempting to purge soft-deleted Cognitive Services account: $account_name"
          az cognitiveservices account purge \
            --location "$location" \
            --resource-group-name "deleted" \
            --account-name "$account_name" \
            --yes || echo "Failed to purge $account_name (may not exist or already purged)"
        fi
      done <<< "$account_names"
    fi
  else
    echo "No soft-deleted Cognitive Services accounts found in location $location"
  fi
}

# Function to purge soft-deleted Machine Learning workspaces
purge_ml_workspaces() {
  echo "=== Checking for soft-deleted Machine Learning workspaces to purge ==="
  
  # Construct resource group name for searching deleted workspaces
  projectNameReplaced="${projectName/prj/project}"
  targetResourceGroup="${commonRGNamePrefix}${projectPrefix}${projectNameReplaced}-${locationSuffix}-${envName}${aifactorySuffixRG}${projectSuffix}"
  
  # List deleted ML workspaces in the subscription and location
  deleted_workspaces=$(az ml workspace list-deleted \
    --location "$location" \
    --query "[?contains(name, '$projectName') || contains(name, 'aif-hub') || contains(name, 'aif-p')].{name:name, location:location, resourceGroup:resourceGroup}" \
    --output json 2>/dev/null || echo "[]")
  
  if [ "$deleted_workspaces" != "[]" ] && [ -n "$deleted_workspaces" ]; then
    echo "Found soft-deleted ML workspaces:"
    echo "$deleted_workspaces"
    
    # Extract workspace details and attempt to purge them
    echo "$deleted_workspaces" | jq -c '.[]' 2>/dev/null | while read -r workspace; do
      workspace_name=$(echo "$workspace" | jq -r '.name' 2>/dev/null)
      workspace_rg=$(echo "$workspace" | jq -r '.resourceGroup' 2>/dev/null)
      
      if [ -n "$workspace_name" ] && [ -n "$workspace_rg" ]; then
        echo "Attempting to purge soft-deleted ML workspace: $workspace_name in RG: $workspace_rg"
        az ml workspace delete \
          --name "$workspace_name" \
          --resource-group "$workspace_rg" \
          --permanently-delete \
          --yes || echo "Failed to purge $workspace_name (may not exist or already purged)"
      fi
    done
  else
    echo "No soft-deleted ML workspaces found for project $projectName in location $location"
  fi
}

# Purge resources based on which tasks performed deletions
if [ "$task_72_deleted" = "true" ]; then
  echo "Task 72 deleted AI Services - attempting to purge soft-deleted Cognitive Services"
  purge_cognitive_services
else
  echo "Task 72 did not delete any resources - skipping Cognitive Services purge"
fi

if [ "$task_71_deleted" = "true" ]; then
  echo "Task 71 deleted AI Foundry Hub/Project - attempting to purge soft-deleted ML workspaces"
  purge_ml_workspaces
else
  echo "Task 71 did not delete any resources - skipping ML workspace purge"
fi

echo "=== Purge Soft-Deleted Resources Completed ==="