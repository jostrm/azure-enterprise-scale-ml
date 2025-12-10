#!/bin/bash

# Script to list all capability hosts in a Foundry Account

# Prompt for required information
read -p "Enter Subscription ID: " subscription_id
read -p "Enter Resource Group name: " resource_group

# Get Azure access token
echo "Getting Azure access token..."
access_token=$(az account get-access-token --query accessToken -o tsv)

if [ -z "$access_token" ]; then
    echo "Error: Failed to get access token. Please make sure you're logged in with 'az login'"
    exit 1
fi

# Construct the API URL to list all capability hosts in the resource group
api_url="https://management.azure.com/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.CognitiveServices/accounts?api-version=2024-10-01"



# Send GET request
response=$(curl -s -X GET \
     -H "Authorization: Bearer ${access_token}" \
     -H "Content-Type: application/json" \
     "${api_url}")

# Check if the curl command was successful
if [ $? -ne 0 ]; then
    echo "Error: Failed to send request."
    exit 1
fi

# Extract account names starting with "aif2" using grep and sed
echo "$response" | grep -o '"name":"aif2[^"]*"' | sed 's/"name":"//g' | sed 's/"//g' | while read -r account_name; do
    if [ -n "$account_name" ]; then
        caphost_url="https://management.azure.com/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts?api-version=2025-04-01-preview"
        caphost_response=$(curl -s -X GET \
            -H "Authorization: Bearer ${access_token}" \
            -H "Content-Type: application/json" \
            "${caphost_url}")
        # Extract capability host names from response
        echo "$caphost_response" | grep -o '"name":"[^"]*"' | sed 's/"name":"//g' | sed 's/"//g' | grep -v "^$"
    fi
done
