#!/bin/bash

# ============================================================================
# AI Factory Email Notifications
# 
# This script sends email notifications to project owners with their
# resource group cost information and attaches the CSV report.
# ============================================================================

set -e

echo "=== AI Factory Email Notifications ==="

# Set up file paths
FINAL_CSV_FILE="/tmp/aifactory_cross_charging_${TIMESTAMP}.csv"

# Verify input file exists
if [ ! -f "$FINAL_CSV_FILE" ]; then
    echo "ERROR: Final CSV file not found: $FINAL_CSV_FILE"
    echo "Make sure the cost data collection script ran successfully."
    exit 1
fi

echo "Preparing email notifications from cost report: $FINAL_CSV_FILE"

# Create temporary directory for email processing
EMAIL_TEMP_DIR="/tmp/email_temp_${TIMESTAMP}"
mkdir -p "$EMAIL_TEMP_DIR"

# Group data by project owner email
echo "Grouping cost data by project owner..."

declare -A owner_data
declare -A owner_totals_current
declare -A owner_totals_forecast

# Read CSV and group by project owner
line_count=0
while IFS=',' read -r rg_name cost_center project_owner current_cost forecasted_cost environment; do
    # Skip header
    ((line_count++))
    if [ $line_count -eq 1 ]; then
        continue
    fi
    
    # Remove quotes
    rg_name=$(echo "$rg_name" | tr -d '"')
    cost_center=$(echo "$cost_center" | tr -d '"')
    project_owner=$(echo "$project_owner" | tr -d '"')
    current_cost=$(echo "$current_cost" | tr -d '"')
    forecasted_cost=$(echo "$forecasted_cost" | tr -d '"')
    environment=$(echo "$environment" | tr -d '"')
    
    # Skip if project owner is unknown or empty
    if [ "$project_owner" = "Unknown" ] || [ -z "$project_owner" ]; then
        echo "  Skipping resource group with unknown owner: $rg_name"
        continue
    fi
    
    # Initialize arrays if first time seeing this owner
    if [ -z "${owner_data[$project_owner]}" ]; then
        owner_data[$project_owner]=""
        owner_totals_current[$project_owner]="0"
        owner_totals_forecast[$project_owner]="0"
    fi
    
    # Add resource group data to owner's list
    owner_data[$project_owner]+="$rg_name|$cost_center|$current_cost|$forecasted_cost\n"
    
    # Add to totals
    owner_totals_current[$project_owner]=$(echo "${owner_totals_current[$project_owner]} + $current_cost" | bc -l)
    owner_totals_forecast[$project_owner]=$(echo "${owner_totals_forecast[$project_owner]} + $forecasted_cost" | bc -l)
    
done < "$FINAL_CSV_FILE"

echo "Found ${#owner_data[@]} unique project owners with cost data"

# Process each project owner
for project_owner in "${!owner_data[@]}"; do
    echo ""
    echo "Processing notifications for: $project_owner"
    
    # Validate email format (basic check)
    if [[ ! "$project_owner" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        echo "  WARNING: Invalid email format for project owner: $project_owner"
        echo "  Skipping email notification..."
        continue
    fi
    
    # Create individual report for this owner
    owner_csv_file="$EMAIL_TEMP_DIR/cost_report_${project_owner//[@.]/_}_${TIMESTAMP}.csv"
    owner_html_file="$EMAIL_TEMP_DIR/email_${project_owner//[@.]/_}_${TIMESTAMP}.html"
    
    # Create CSV header
    echo "resource_group,cost_center,current_cost,forecasted_cost" > "$owner_csv_file"
    
    # Add owner's resource groups to CSV
    echo -e "${owner_data[$project_owner]}" | while IFS='|' read -r rg_name cost_center current_cost forecasted_cost; do
        if [ -n "$rg_name" ]; then
            echo "\"$rg_name\",\"$cost_center\",\"$current_cost\",\"$forecasted_cost\"" >> "$owner_csv_file"
        fi
    done
    
    # Format totals
    total_current=$(printf "%.2f" "${owner_totals_current[$project_owner]}")
    total_forecast=$(printf "%.2f" "${owner_totals_forecast[$project_owner]}")
    
    echo "  Current total: \$${total_current}"
    echo "  Forecasted total: \$${total_forecast}"
    
    # Create HTML email content
    cat > "$owner_html_file" << EOF
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background-color: #0078d4; color: white; padding: 20px; border-radius: 5px; }
        .content { margin: 20px 0; }
        .summary { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0; }
        .cost-table { border-collapse: collapse; width: 100%; margin: 15px 0; }
        .cost-table th, .cost-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .cost-table th { background-color: #f2f2f2; }
        .total-row { font-weight: bold; background-color: #e7f3ff; }
        .footer { margin-top: 30px; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <h1>AI Factory Cross-Charging Report</h1>
        <p>Monthly Cost Summary for ${ENVIRONMENT^} Environment</p>
    </div>
    
    <div class="content">
        <p>Dear Project Owner,</p>
        
        <p>This is your monthly AI Factory cross-charging report for the <strong>${ENVIRONMENT^}</strong> environment, generated on <strong>$(date +"%B %d, %Y")</strong>.</p>
        
        <div class="summary">
            <h3>📊 Cost Summary</h3>
            <ul>
                <li><strong>Current Month Cost:</strong> \$${total_current}</li>
                <li><strong>Forecasted Next Month:</strong> \$${total_forecast}</li>
                <li><strong>Environment:</strong> ${ENVIRONMENT^}</li>
                <li><strong>Report Date:</strong> $(date +"%Y-%m-%d %H:%M:%S UTC")</li>
            </ul>
        </div>
        
        <h3>💰 Resource Group Cost Details</h3>
        <table class="cost-table">
            <thead>
                <tr>
                    <th>Resource Group</th>
                    <th>Cost Center</th>
                    <th>Current Cost</th>
                    <th>Forecasted Cost</th>
                </tr>
            </thead>
            <tbody>
EOF
    
    # Add resource group rows to HTML
    echo -e "${owner_data[$project_owner]}" | while IFS='|' read -r rg_name cost_center current_cost forecasted_cost; do
        if [ -n "$rg_name" ]; then
            cat >> "$owner_html_file" << EOF
                <tr>
                    <td>$rg_name</td>
                    <td>$cost_center</td>
                    <td>\$${current_cost}</td>
                    <td>\$${forecasted_cost}</td>
                </tr>
EOF
        fi
    done
    
    # Complete HTML
    cat >> "$owner_html_file" << EOF
                <tr class="total-row">
                    <td><strong>TOTAL</strong></td>
                    <td></td>
                    <td><strong>\$${total_current}</strong></td>
                    <td><strong>\$${total_forecast}</strong></td>
                </tr>
            </tbody>
        </table>
        
        <h3>📎 Additional Information</h3>
        <ul>
            <li><strong>Data Source:</strong> Azure Cost Management API</li>
            <li><strong>Subscription:</strong> ${SUBSCRIPTION_ID}</li>
            <li><strong>Report Archive:</strong> Available in AI Factory Data Lake</li>
            <li><strong>Next Report:</strong> $(date -d "next month" +"%B %d, %Y")</li>
        </ul>
        
        <p>The detailed CSV report is attached to this email and has been archived in the AI Factory data lake at:</p>
        <p><code>https://${DATALAKE_NAME}.dfs.core.windows.net/${LAKE_CONTAINER_NAME}/${TARGET_BLOB_PATH}</code></p>
        
        <div class="footer">
            <p>This report was automatically generated by the AI Factory Cross-Charging Pipeline.</p>
            <p>For questions or concerns, please contact your AI Factory administrator.</p>
            <p><em>Generated at: $(date +"%Y-%m-%d %H:%M:%S UTC")</em></p>
        </div>
    </div>
</body>
</html>
EOF
    
    echo "  ✓ Created personalized report: $owner_csv_file"
    echo "  ✓ Created HTML email: $owner_html_file"
    
    # Here we would normally send the email using Azure Communication Services
    # or another email service. For now, we'll simulate the email sending.
    
    echo "  📧 Sending email notification to: $project_owner"
    echo "     Subject: AI Factory Cross-Charging Report - ${ENVIRONMENT^} Environment - $(date +"%B %Y")"
    echo "     Attachment: $(basename "$owner_csv_file")"
    echo "     Total Cost: \$${total_current} (Current) / \$${total_forecast} (Forecast)"
    
    # In a real implementation, you would use one of these approaches:
    # 1. Azure Communication Services Email API
    # 2. Azure Logic Apps
    # 3. SendGrid or other email service
    # 4. Office 365 Graph API
    
    # For demonstration, we'll create a command that would send the email:
    cat > "$EMAIL_TEMP_DIR/send_email_${project_owner//[@.]/_}.sh" << EOF
#!/bin/bash
# Email sending command for $project_owner
# This script would contain the actual email sending logic

# Example using Azure Communication Services (placeholder):
# az communication email send \\
#   --sender "noreply@yourcompany.com" \\
#   --to "$project_owner" \\
#   --subject "AI Factory Cross-Charging Report - ${ENVIRONMENT^} Environment - $(date +"%B %Y")" \\
#   --html-content "\$(cat '$owner_html_file')" \\
#   --attachments '$owner_csv_file'

echo "Email would be sent to: $project_owner"
echo "Subject: AI Factory Cross-Charging Report - ${ENVIRONMENT^} Environment - $(date +"%B %Y")"
echo "HTML content: $owner_html_file"
echo "Attachment: $owner_csv_file"
EOF
    
    chmod +x "$EMAIL_TEMP_DIR/send_email_${project_owner//[@.]/_}.sh"
    
    echo "  ✓ Email notification prepared for $project_owner"
    
done

echo ""
echo "=== Email Notification Summary ==="
echo "✓ Email notifications prepared for ${#owner_data[@]} project owners"
echo "📁 Email files created in: $EMAIL_TEMP_DIR"
echo ""

# List all prepared emails
echo "Prepared email notifications:"
for project_owner in "${!owner_data[@]}"; do
    total_current=$(printf "%.2f" "${owner_totals_current[$project_owner]}")
    total_forecast=$(printf "%.2f" "${owner_totals_forecast[$project_owner]}")
    echo "  📧 $project_owner - Current: \$${total_current}, Forecast: \$${total_forecast}"
done

echo ""
echo "Note: Email sending is simulated in this implementation."
echo "To enable actual email sending, integrate with:"
echo "  • Azure Communication Services"
echo "  • Azure Logic Apps"
echo "  • SendGrid or other email service provider"
echo "  • Office 365 Graph API"

echo ""
echo "Email preparation completed successfully!"