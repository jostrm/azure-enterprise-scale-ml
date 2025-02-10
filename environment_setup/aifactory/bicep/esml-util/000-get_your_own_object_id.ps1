# Cloud shell (PS)
Connect-AzAccount -UseDeviceAuthentication
(Get-AzADUser -UserPrincipalName (Get-AzContext).Account).Id

# Cloud shell (Bash)
#az login
#az ad signed-in-user show --query objectId -o tsv
