#$PSVersionTable.PSVersion

# 0) Connect to Azure
Connect-AzAccount

# 1) Set Subscription
$context = Get-AzSubscription -SubscriptionId 'todo_subID' # 
Set-AzContext $context

# 2) Set RG
#Set-AzDefault -ResourceGroupName 'esml-project001-test-002-rg'