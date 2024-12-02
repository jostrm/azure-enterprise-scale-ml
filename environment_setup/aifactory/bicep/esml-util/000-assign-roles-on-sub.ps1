## .\000-assign-roles-on-sub.ps1 -emailAddresses "user1@example.com", "user2@example.com", "user3@example.com"
param (
    [Parameter(Mandatory = $true, HelpMessage = "Subscription ID")][string]$subscriptionId,
    [Parameter(Mandatory = $true, HelpMessage = "Subscription ID")][string[]]$emailAddresses
)


$context = Get-AzSubscription -SubscriptionId $subscriptionId # Define the subscription ID
Set-AzContext $context

# Define the scope
$scope = "/subscriptions/$subscriptionId"

$roles = @(
    "Cognitive services Custom Vision Contributor",
    "Search Index Data Contributor",
    "Storage Blob Data Contributor",
    "Contributor"
)
# Define the list of email addresses
#$emailAddresses = @(
#    "a@acme.com",
    #"b@acme.com"
#)


# Loop through each email address and assign the role
foreach ($email in $emailAddresses) {
    foreach ($role in $roles) {
        az role assignment create --assignee $email --role $role --scope $scope
    }
}