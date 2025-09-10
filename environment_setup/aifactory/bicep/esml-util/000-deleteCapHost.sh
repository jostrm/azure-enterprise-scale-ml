#!/bin/bash

# Script to delete the capability host

# Prompt for required information
read -p "Enter Subscription ID: " subscription_id
read -p "Enter Resource Group name: " resource_group
read -p "Enter Foundry Account or Project name: " account_name
read -p "Enter CapabilityHost name: " caphost_name

# Get Azure access token
echo "Getting Azure access token..."
access_token=$(az account get-access-token --query accessToken -o tsv)

if [ -z "$access_token" ]; then
    echo "Error: Failed to get access token. Please make sure you're logged in with 'az login'"
    exit 1
fi

# Construct the API URL
api_url="https://management.azure.com/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.CognitiveServices/accounts/${account_name}/capabilityHosts/${caphost_name}?api-version=2025-04-01-preview"

echo "Deleting capability host: ${caphost_name}"
echo "API URL: ${api_url}"
 
# Send DELETE request and capture headers
echo "Sending DELETE request..."
response_headers=$(mktemp)
http_code=$(curl -X DELETE \
     -H "Authorization: Bearer ${access_token}" \
     -H "Content-Type: application/json" \
     -D "${response_headers}" \
     -s \
     -w "%{http_code}" \
     "${api_url}")
     
# Check if the curl command was successful
if [ $? -ne 0 ]; then
    echo -e "\nError: Failed to send deletion request."
    rm -f "${response_headers}"
    exit 1
fi

echo "HTTP Response Code: ${http_code}"

# Check for immediate success (204 No Content means successful deletion)
if [ "${http_code}" = "204" ]; then
    echo -e "\nCapability host deleted successfully (immediate deletion)."
    rm -f "${response_headers}"
    exit 0
fi

# For other success codes, look for async operation
if [ "${http_code}" = "202" ]; then
    # Extract the Azure-AsyncOperation URL from the response headers
    operation_url=$(grep -i "Azure-AsyncOperation" "${response_headers}" | cut -d' ' -f2 | tr -d '\r')
    
    if [ -z "${operation_url}" ]; then
        echo -e "\nError: Expected async operation URL but could not find it in the response."
        cat "${response_headers}"
        rm -f "${response_headers}"
        exit 1
    fi
else
    echo -e "\nUnexpected HTTP response code: ${http_code}"
    cat "${response_headers}"
    rm -f "${response_headers}"
    exit 1
fi

rm -f "${response_headers}"

echo -e "\nCapability host deletion request initiated."
echo "Monitoring operation: ${operation_url}"

# Poll the operation URL until the operation completes
status="InProgress"
while [ "${status}" = "InProgress" ] || [ "${status}" = "Running" ]; do
    echo "Checking operation status..."
    access_token=$(az account get-access-token --query accessToken -o tsv)
    # Get the operation status
    operation_response=$(curl -s \
        -H "Authorization: Bearer ${access_token}" \
        -H "Content-Type: application/json" \
        "${operation_url}")

    # Check for transient errors
    error_code=$(echo "${operation_response}" | jq -r '.error.code // empty')
    if [ "${error_code}" = "TransientError" ]; then
        echo "Transient error encountered. Continuing to poll..."
        sleep 10
        continue
    fi
    # Extract the status from the response using jq
    status=$(echo "${operation_response}" | jq -r '.status')

    if [ -z "${status}" ]; then
        echo "Error: Could not determine operation status."
        echo "Response: ${operation_response}"
        exit 1
    fi

    echo "Current status: ${status}"

    if [ "${status}" = "InProgress" ] || [ "${status}" = "Running" ]; then
        echo "Operation still in progress. Waiting 10 seconds before checking again..."
        sleep 10
    fi
done

# Check the final status
if [ "${status}" = "Succeeded" ]; then
    echo -e "\nCapability host deletion completed successfully."
else
    echo -e "\nCapability host deletion failed with status: ${status}"
    echo "Response: ${operation_response}"
    exit 1
fi