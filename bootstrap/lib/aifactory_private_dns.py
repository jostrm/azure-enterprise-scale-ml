#!/usr/bin/env python3
"""Build central AI Factory private-DNS zones and ALZ initiative parameters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parameter_zone_names(location: str, location_short: str) -> dict[str, str]:
    return {
        "azureAcrPrivateDnsZoneId": "privatelink.azurecr.io",
        "azureAppPrivateDnsZoneId": "privatelink.azconfig.io",
        "azureAppServicesPrivateDnsZoneId": "privatelink.azurewebsites.net",
        "azureArcGuestconfigurationPrivateDnsZoneId": "privatelink.guestconfiguration.azure.com",
        "azureArcHybridResourceProviderPrivateDnsZoneId": "privatelink.his.arc.azure.com",
        "azureArcKubernetesConfigurationPrivateDnsZoneId": "privatelink.dp.kubernetesconfiguration.azure.com",
        "azureAsrPrivateDnsZoneId": "privatelink.siterecovery.windowsazure.com",
        "azureAutomationDSCHybridPrivateDnsZoneId": "privatelink.azure-automation.net",
        "azureAutomationWebhookPrivateDnsZoneId": "privatelink.azure-automation.net",
        "azureBatchPrivateDnsZoneId": "privatelink.batch.azure.com",
        "azureBotServicePrivateDnsZoneId": "privatelink.directline.botframework.com",
        "azureCognitiveSearchPrivateDnsZoneId": "privatelink.search.windows.net",
        "azureCognitiveServicesPrivateDnsZoneId": "privatelink.cognitiveservices.azure.com",
        "azureCosmosCassandraPrivateDnsZoneId": "privatelink.cassandra.cosmos.azure.com",
        "azureCosmosGremlinPrivateDnsZoneId": "privatelink.gremlin.cosmos.azure.com",
        "azureCosmosMongoPrivateDnsZoneId": "privatelink.mongo.cosmos.azure.com",
        "azureCosmosSQLPrivateDnsZoneId": "privatelink.documents.azure.com",
        "azureCosmosTablePrivateDnsZoneId": "privatelink.table.cosmos.azure.com",
        "azureDataFactoryPortalPrivateDnsZoneId": "privatelink.adf.azure.com",
        "azureDataFactoryPrivateDnsZoneId": "privatelink.datafactory.azure.net",
        "azureDatabricksPrivateDnsZoneId": "privatelink.azuredatabricks.net",
        "azureDiskAccessPrivateDnsZoneId": "privatelink.blob.core.windows.net",
        "azureEventGridDomainsPrivateDnsZoneId": "privatelink.eventgrid.azure.net",
        "azureEventGridTopicsPrivateDnsZoneId": "privatelink.eventgrid.azure.net",
        "azureEventHubNamespacePrivateDnsZoneId": "privatelink.servicebus.windows.net",
        "azureFilePrivateDnsZoneId": "privatelink.afs.azure.net",
        "azureHDInsightPrivateDnsZoneId": "privatelink.azurehdinsight.net",
        "azureIotCentralPrivateDnsZoneId": "privatelink.azureiotcentral.com",
        "azureIotDeviceupdatePrivateDnsZoneId": "privatelink.api.adu.microsoft.com",
        "azureIotHubsPrivateDnsZoneId": "privatelink.azure-devices.net",
        "azureIotPrivateDnsZoneId": "privatelink.azure-devices-provisioning.net",
        "azureKeyVaultPrivateDnsZoneId": "privatelink.vaultcore.azure.net",
        "azureMachineLearningWorkspacePrivateDnsZoneId": "privatelink.api.azureml.ms",
        "azureMachineLearningWorkspaceSecondPrivateDnsZoneId": "privatelink.notebooks.azure.net",
        "azureManagedGrafanaWorkspacePrivateDnsZoneId": "privatelink.grafana.azure.com",
        "azureMediaServicesKeyPrivateDnsZoneId": "privatelink.media.azure.net",
        "azureMediaServicesLivePrivateDnsZoneId": "privatelink.media.azure.net",
        "azureMediaServicesStreamPrivateDnsZoneId": "privatelink.media.azure.net",
        "azureMigratePrivateDnsZoneId": "privatelink.prod.migration.windowsazure.com",
        "azureMonitorPrivateDnsZoneId1": "privatelink.monitor.azure.com",
        "azureMonitorPrivateDnsZoneId2": "privatelink.oms.opinsights.azure.com",
        "azureMonitorPrivateDnsZoneId3": "privatelink.ods.opinsights.azure.com",
        "azureMonitorPrivateDnsZoneId4": "privatelink.agentsvc.azure-automation.net",
        "azureMonitorPrivateDnsZoneId5": "privatelink.blob.core.windows.net",
        "azureRedisCachePrivateDnsZoneId": "privatelink.redis.cache.windows.net",
        "azureServiceBusNamespacePrivateDnsZoneId": "privatelink.servicebus.windows.net",
        "azureSignalRPrivateDnsZoneId": "privatelink.service.signalr.net",
        "azureSiteRecoveryBackupPrivateDnsZoneID": f"privatelink.{location_short}.backup.windowsazure.com",
        "azureSiteRecoveryBlobPrivateDnsZoneID": "privatelink.blob.core.windows.net",
        "azureSiteRecoveryQueuePrivateDnsZoneID": "privatelink.queue.core.windows.net",
        "azureStorageBlobPrivateDnsZoneId": "privatelink.blob.core.windows.net",
        "azureStorageBlobSecPrivateDnsZoneId": "privatelink.blob.core.windows.net",
        "azureStorageDFSPrivateDnsZoneId": "privatelink.dfs.core.windows.net",
        "azureStorageDFSSecPrivateDnsZoneId": "privatelink.dfs.core.windows.net",
        "azureStorageFilePrivateDnsZoneId": "privatelink.file.core.windows.net",
        "azureStorageQueuePrivateDnsZoneId": "privatelink.queue.core.windows.net",
        "azureStorageQueueSecPrivateDnsZoneId": "privatelink.queue.core.windows.net",
        "azureStorageStaticWebPrivateDnsZoneId": "privatelink.web.core.windows.net",
        "azureStorageStaticWebSecPrivateDnsZoneId": "privatelink.web.core.windows.net",
        "azureStorageTablePrivateDnsZoneId": "privatelink.table.core.windows.net",
        "azureStorageTableSecondaryPrivateDnsZoneId": "privatelink.table.core.windows.net",
        "azureSynapseDevPrivateDnsZoneId": "privatelink.dev.azuresynapse.net",
        "azureSynapseSQLPrivateDnsZoneId": "privatelink.sql.azuresynapse.net",
        "azureSynapseSQLODPrivateDnsZoneId": "privatelink.sql.azuresynapse.net",
        "azureVirtualDesktopHostpoolPrivateDnsZoneId": "privatelink.wvd.microsoft.com",
        "azureVirtualDesktopWorkspacePrivateDnsZoneId": "privatelink.wvd.microsoft.com",
        "azureWebPrivateDnsZoneId": "privatelink.webpubsub.azure.com",
    }


def configuration(
    subscription_id: str,
    resource_group: str,
    location: str,
    location_short: str,
) -> dict[str, object]:
    mapping = parameter_zone_names(location, location_short)
    extra_zones = {
        f"privatelink.{location}.azmk8s.io",
        f"privatelink.{location}.azurecontainerapps.io",
        f"privatelink.{location}.kusto.windows.net",
        "privatelink.azure-api.net",
        "privatelink.database.windows.net",
        "privatelink.mongo.cosmos.azure.com",
        "privatelink.openai.azure.com",
        "privatelink.postgres.database.azure.com",
        "privatelink.services.ai.azure.com",
    }
    zones = sorted(set(mapping.values()) | extra_zones)
    base = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        "/providers/Microsoft.Network/privateDnsZones"
    )
    parameters = {
        parameter: {"value": f"{base}/{zone}"}
        for parameter, zone in mapping.items()
    }
    return {
        "zones": [{"name": zone} for zone in zones],
        "assignmentParameters": parameters,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--location-short", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            configuration(
                args.subscription_id,
                args.resource_group,
                args.location,
                args.location_short,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
