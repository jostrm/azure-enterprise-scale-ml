# 21, should be 27 (privatelink.services.ai.azure.com is NEW)
$privateZones = ('privatelink.services.ai.azure.com','privatelink.adf.azure.com','privatelink.api.azureml.ms','privatelink.azurecr.io','privatelink.blob.core.windows.net','privatelink.database.windows.net','privatelink.datafactory.azure.net','privatelink.file.core.windows.net','privatelink.notebooks.azure.net','privatelink.queue.core.windows.net','privatelink.table.core.windows.net','privatelink.vaultcore.azure.net','privatelink.search.windows.net','privatelink.azuredatabricks.net','privatelink.databricks.azure.us','privatelink.servicebus.windows.net','privatelink.eventgrid.azure.net','privatelink.monitor.azure.com','privatelink.oms.opinsights.azure.com','privatelink.ods.opinsights.azure.com','privatelink.agentsvc.azure-automation.net') 
# or use Get-AzPrivateDnsZone with the appropriate parameters

$linkZonesToVnet = $true
if ($linkZonesToVnet)
{
    $virtualNetwork = Get-AzVirtualNetwork -ResourceGroupName $vnetNameResourceGroupName -Name $vnetName

    foreach ($zoneName in $privateZones)
    {
        # silence the error, so the commandlet doesnt throw the error
        $link = Get-AzPrivateDnsVirtualNetworkLink -ResourceGroupName $resourceGroupName -ZoneName $zoneName -Name "link-$location" -ErrorAction SilentlyContinue
        if ($null -eq $link)
        {
            "creating vnet link for $zoneName"
            $link = New-AzPrivateDnsVirtualNetworkLink -ResourceGroupName $resourceGroupName -ZoneName $zoneName  -Name "link-$location" -VirtualNetworkId $virtualNetwork.Id #-EnableRegistration
        }
    }
}