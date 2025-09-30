#!/bin/bash

# ============================================================================
# AI Factory Cost Data Collection
# 
# This script collects current and forecasted cost data for discovered
# AI Factory resource groups using Azure Cost Management APIs.
# ============================================================================

set -e

echo "=== AI Factory Cost Data Collection ==="

# Set up file paths
RG_INFO_FILE="/tmp/rg_info_${TIMESTAMP}.csv"
COST_DATA_FILE="/tmp/cost_data_${TIMESTAMP}.csv"
FINAL_CSV_FILE="/tmp/aifactory_cross_charging_${TIMESTAMP}.csv"

# Verify input file exists
if [ ! -f "$RG_INFO_FILE" ]; then
    echo "ERROR: Resource group info file not found: $RG_INFO_FILE"
    echo "Make sure the resource group discovery script ran successfully."
    exit 1
fi

echo "Reading resource group information from: $RG_INFO_FILE"

# Initialize final CSV with headers
echo "resource_group,cost_center,project_owner,current_cost,forecasted_cost,aifactory_environment" > "$FINAL_CSV_FILE"

# Set date ranges for cost queries
CURRENT_DATE=$(date +"%Y-%m-%d")
MONTH_START=$(date +"%Y-%m-01")
NEXT_MONTH_START=$(date -d "next month" +"%Y-%m-01")
NEXT_MONTH_END=$(date -d "$(date -d "next month" +"%Y-%m-01") + 1 month - 1 day" +"%Y-%m-%d")

echo "Cost analysis period:"
echo "  Current month: $MONTH_START to $CURRENT_DATE"
echo "  Forecast period: $NEXT_MONTH_START to $NEXT_MONTH_END"

# Process each resource group
line_count=0
processed_count=0

while IFS=',' read -r rg_name location cost_center project_owner environment project_number; do
    # Skip header
    ((line_count++))
    if [ $line_count -eq 1 ]; then
        continue
    fi
    
    # Remove quotes from variables
    rg_name=$(echo "$rg_name" | tr -d '"')
    cost_center=$(echo "$cost_center" | tr -d '"')
    project_owner=$(echo "$project_owner" | tr -d '"')
    environment=$(echo "$environment" | tr -d '"')
    
    echo ""
    echo "Processing resource group: $rg_name"
    echo "  Environment: $environment"
    echo "  Cost Center: $cost_center"
    echo "  Project Owner: $project_owner"
    
    # Get current month costs
    echo "  Fetching current month costs..."
    current_cost="0.00"
    
    # Query current month actual costs
    cost_query_result=$(az costmanagement query \
        --type "ActualCost" \
        --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg_name" \
        --timeframe "Custom" \
        --time-period from="$MONTH_START" to="$CURRENT_DATE" \
        --dataset-aggregation name="Cost" function="Sum" \
        --dataset-grouping name="ResourceGroup" type="Dimension" \
        --query "properties.rows" \
        --output json 2>/dev/null || echo "[]")
    
    if [ "$cost_query_result" != "[]" ] && [ "$cost_query_result" != "null" ]; then
        # Extract cost value from the result
        current_cost=$(echo "$cost_query_result" | jq -r '.[0][0] // "0.00"' 2>/dev/null || echo "0.00")
        if [ "$current_cost" = "null" ] || [ -z "$current_cost" ]; then
            current_cost="0.00"
        fi
    fi
    
    echo "  Current month cost: \$${current_cost}"
    
    # Get forecasted costs for next month
    echo "  Fetching forecasted costs..."
    forecasted_cost="0.00"
    
    # Try to get forecast data (Note: Azure forecasting may have limited availability)
    forecast_query_result=$(az costmanagement forecast \
        --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$rg_name" \
        --timeframe "Custom" \
        --time-period from="$NEXT_MONTH_START" to="$NEXT_MONTH_END" \
        --dataset-aggregation name="Cost" function="Sum" \
        --dataset-grouping name="ResourceGroup" type="Dimension" \
        --query "properties.rows" \
        --output json 2>/dev/null || echo "[]")
    
    if [ "$forecast_query_result" != "[]" ] && [ "$forecast_query_result" != "null" ]; then
        # Extract forecasted cost value
        forecasted_cost=$(echo "$forecast_query_result" | jq -r '.[0][0] // "0.00"' 2>/dev/null || echo "0.00")
        if [ "$forecasted_cost" = "null" ] || [ -z "$forecasted_cost" ]; then
            forecasted_cost="0.00"
        fi
    else
        # If forecast is not available, estimate based on current month usage
        if [ "$current_cost" != "0.00" ]; then
            # Simple estimation: current cost * (days in next month / days passed in current month)
            days_passed=$(( $(date +%d) - 1 ))
            if [ $days_passed -gt 0 ]; then
                days_in_next_month=$(date -d "$NEXT_MONTH_START + 1 month - 1 day" +%d)
                forecasted_cost=$(echo "scale=2; $current_cost * $days_in_next_month / $days_passed" | bc -l 2>/dev/null || echo "$current_cost")
            else
                forecasted_cost="$current_cost"
            fi
        fi
    fi
    
    echo "  Forecasted cost: \$${forecasted_cost}"
    
    # Format costs to ensure they have 2 decimal places
    current_cost=$(printf "%.2f" "$current_cost" 2>/dev/null || echo "0.00")
    forecasted_cost=$(printf "%.2f" "$forecasted_cost" 2>/dev/null || echo "0.00")
    
    # Add to final CSV
    echo "\"$rg_name\",\"$cost_center\",\"$project_owner\",\"$current_cost\",\"$forecasted_cost\",\"$environment\"" >> "$FINAL_CSV_FILE"
    
    ((processed_count++))
    echo "  ✓ Cost data collected for $rg_name"
    
    # Add a small delay to avoid API rate limiting
    sleep 2
    
done < "$RG_INFO_FILE"

echo ""
echo "=== Cost Data Collection Summary ==="
echo "Total resource groups processed: $processed_count"
echo "Cost data saved to: $FINAL_CSV_FILE"

# Display summary report
if [ -f "$FINAL_CSV_FILE" ] && [ $processed_count -gt 0 ]; then
    echo ""
    echo "=== Cost Summary Report ==="
    echo "Resource Group | Current Cost | Forecasted Cost | Cost Center | Environment"
    echo "---------------|--------------|-----------------|-------------|------------"
    
    total_current=0
    total_forecast=0
    
    # Skip header and display data
    tail -n +2 "$FINAL_CSV_FILE" | while IFS=',' read -r rg_name cost_center project_owner current_cost forecasted_cost environment; do
        # Remove quotes
        rg_name=$(echo "$rg_name" | tr -d '"')
        cost_center=$(echo "$cost_center" | tr -d '"')
        current_cost=$(echo "$current_cost" | tr -d '"')
        forecasted_cost=$(echo "$forecasted_cost" | tr -d '"')
        environment=$(echo "$environment" | tr -d '"')
        
        printf "%-40s | \$%-11s | \$%-14s | %-11s | %s\n" \
            "$(echo "$rg_name" | cut -c1-39)" \
            "$current_cost" \
            "$forecasted_cost" \
            "$cost_center" \
            "$environment"
    done
    
    # Calculate totals
    total_current=$(tail -n +2 "$FINAL_CSV_FILE" | cut -d',' -f4 | tr -d '"' | awk '{sum += $1} END {printf "%.2f", sum}')
    total_forecast=$(tail -n +2 "$FINAL_CSV_FILE" | cut -d',' -f5 | tr -d '"' | awk '{sum += $1} END {printf "%.2f", sum}')
    
    echo "---------------|--------------|-----------------|-------------|------------"
    printf "%-40s | \$%-11s | \$%-14s | %-11s | %s\n" \
        "TOTAL" \
        "$total_current" \
        "$total_forecast" \
        "" \
        ""
    
    echo ""
    echo "Final cost report file: $FINAL_CSV_FILE"
else
    echo "ERROR: No cost data was collected!"
    exit 1
fi

# Export file path for next script
export FINAL_CSV_FILE