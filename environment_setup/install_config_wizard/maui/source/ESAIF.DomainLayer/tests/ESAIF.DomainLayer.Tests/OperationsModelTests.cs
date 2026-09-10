using System.Text.Json;
using ESAIF.BaseLayer.Monitoring;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.DomainLayer.Tests;

public sealed class OperationsModelTests
{
    private static readonly JsonSerializerOptions JsonOptions =
        new(JsonSerializerDefaults.Web);

    [Fact]
    public void FactoryMonitoringRegions_AreSeparateFromKnownConfiguredRegions()
    {
        var overview = JsonSerializer.Deserialize<OperationsOverview>(
            """{"factory":{"active_regions":["eastus2","swedencentral"],"monitoring_regions":["swedencentral"]}}""",
            JsonOptions)!;
        Assert.Equal(new[] { "swedencentral" }, overview.Factory.MonitoringRegions);
        Assert.Equal(2, overview.Factory.ActiveRegions.Count);
    }

    [Fact]
    public void RegionFindings_KeepRunProvenanceAndSkuLists()
    {
        const string json = """
        {"name":"eastus2","pipeline_findings":[{"id":"e1","kind":"capacity","service":"Azure AI Search",
        "status":"failed","skus":["basic","standard","standard2"],"source":"user_reported","observed_at":null,
        "run_id":null,"message":"Last reported run failed.","recorded_at":"2026-09-07T15:24:13Z"}]}
        """;
        var region = JsonSerializer.Deserialize<AzureRegionInfo>(json, JsonOptions)!;
        var finding = Assert.Single(region.PipelineFindings);
        Assert.Equal(new[] { "basic", "standard", "standard2" }, finding.Skus);
        Assert.Null(finding.ObservedAt);
        Assert.Equal("user_reported", finding.Source);
        Assert.Equal("failed", finding.Status);
    }

    [Fact]
    public void FactoryDashboardUrl_DeserializesWithoutRewritingPrivateDashboardFragments()
    {
        const string address = "https://portal.azure.com/#@example.onmicrosoft.com/dashboard/private/test";
        var json = JsonSerializer.Serialize(new { factory = new { dashboard_url = address } });
        var overview = JsonSerializer.Deserialize<OperationsOverview>(json, JsonOptions)!;
        Assert.Equal(address, overview.Factory.DashboardUrl);
    }

    [Fact]
    public void Overview_DeserializesRealisticNestedContract()
    {
        const string json = """
        {
          "generated_at": "2026-09-05T15:00:00Z",
          "source": "mixed",
          "warning": "Prompt telemetry is seeded.",
          "factory": {
            "folder": "C:\\factory",
            "name": "esaif-demo",
            "orchestrator": "ado",
            "active_regions": ["swedencentral"],
            "subscriptions": {"dev": "sub-1"},
            "subscription_ids": ["sub-1"],
            "project_numbers": ["001"],
            "prefix_rg": "esaif",
            "suffix_rg": "demo",
            "variables_found": "1",
            "project_count": "1",
            "resource_group_count": 1,
            "resource_count": "2"
          },
          "regions": [{
            "name": "swedencentral",
            "display_name": "Sweden Central",
            "geography": "Europe",
            "physical_location": "Gävle",
            "latitude": "60.67",
            "longitude": 17.14,
            "normalized_latitude": 0.674111,
            "normalized_longitude": "0.095222",
            "has_factory": 1,
            "factory_count": "1",
            "project_count": 1,
            "resource_count": "2",
            "status": "active"
          }],
          "projects": [{
            "project_number": "001",
            "display_name": "Project 001",
            "environments": [{
              "environment": "dev",
              "status": "active",
              "resource_group": "esaif-project001-dev-rg",
              "resource_groups": ["esaif-project001-dev-rg"],
              "region": "swedencentral",
              "regions": ["swedencentral"],
              "subscription_id": "sub-1",
              "resource_count": "2"
            }],
            "resource_count": 2
          }],
          "common_resource_groups": [{
            "name": "esaif-common-rg",
            "location": "swedencentral",
            "subscriptionId": "sub-1",
            "tags": null
          }],
          "resource_inventory": {
            "source": "azure",
            "collected_at": "2026-09-05T15:00:00Z",
            "subscriptions": ["sub-1"],
            "subscription_count": 1,
            "resource_group_count": "1",
            "resource_count": 1,
            "resource_groups": [],
            "resources": [{
              "id": "/subscriptions/sub-1/resourceGroups/rg/providers/type/name",
              "name": "account",
              "type": "Microsoft.CognitiveServices/accounts",
              "location": "swedencentral",
              "resourceGroup": "esaif-project001-dev-rg",
              "subscriptionId": "sub-1",
              "provisioningState": "Succeeded",
              "tags": {"owner": "platform", "priority": 2}
            }]
          },
          "monitoring": {
            "resources_by_service_type": {
              "labels": ["Microsoft.CognitiveServices/accounts"],
              "values": ["1"],
              "source": "azure",
              "chart_type": "pie"
            },
            "tokens_over_time": {
              "labels": ["2026-09-05"],
              "series": {
                "input": ["100"],
                "cached_input": [25],
                "output": ["40"]
              },
              "source": "seeded",
              "chart_type": "line",
              "stacked": true
            },
            "success_error_rate": {
              "labels": ["2026-09-05"],
              "series": {"success": [9], "error": [1]},
              "success_rate": "90",
              "error_rate": 10,
              "source": "seeded",
              "chart_type": "line"
            }
          },
          "operation_configs": [{
            "project_number": "001",
            "environment": "dev",
            "kind": "rag",
            "config": {"retrieval_top_k": 5},
            "updated_at": "2026-09-05T15:00:00Z"
          }],
          "factory_action_requests": [],
          "prompt_summary": {
            "source": "seeded",
            "record_count": "10",
            "success_count": 9,
            "error_count": "1",
            "input_tokens": "1000",
            "cached_input_tokens": 250,
            "output_tokens": "400",
            "models": ["gpt-4o"],
            "categories": ["Coding"]
          }
        }
        """;

        var overview = JsonSerializer.Deserialize<OperationsOverview>(json, JsonOptions);

        Assert.NotNull(overview);
        Assert.Equal("mixed", overview.Source);
        Assert.Equal("Prompt telemetry is seeded.", overview.Warning);
        Assert.True(overview.Factory.VariablesFound);
        Assert.Equal(2, overview.Factory.ResourceCount);
        Assert.Equal(60.67, overview.Regions.Single().Latitude);
        Assert.Equal(2, overview.Projects.Single().Environments.Single().ResourceCount);
        Assert.Empty(overview.CommonResourceGroups.Single().Tags);
        Assert.Equal(2, overview.ResourceInventory.Resources.Single().Tags["priority"]!.GetValue<int>());
        Assert.Equal(1, overview.Monitoring.ResourcesByServiceType.Values.Single());
        Assert.Equal(25, overview.Monitoring.TokensOverTime.Series["cached_input"].Single());
        Assert.Equal(90, overview.Monitoring.SuccessErrorRate.SuccessRate);
        Assert.Equal(5, overview.OperationConfigs.Single().Config["retrieval_top_k"]!.GetValue<int>());
        Assert.Equal(250, overview.PromptSummary.CachedInputTokens);
        MonitoringDataAdapter.ValidateAndAlign(overview.Monitoring.TokensOverTime);
    }

    [Fact]
    public void PromptSearch_DeserializesTokenBreakdownFiltersAndWarning()
    {
        const string json = """
        {
          "rows": [{
            "operation_id": "operation-1",
            "conversation_id": "conversation-1",
            "response_id": "response-1",
            "timestamp": "2026-09-05T15:00:00Z",
            "project_number": "001",
            "environment": "dev",
            "region": "swedencentral",
            "model": "gpt-4o",
            "category": "Coding",
            "prompt": "Refactor this API",
            "response": "Done",
            "input_tokens": "120",
            "cached_input_tokens": "20",
            "output_tokens": 30,
            "total_tokens": "150",
            "latency_ms": "425.5",
            "success": true,
            "error_type": null,
            "source": "seeded"
          }],
          "total": "1",
          "limit": 25,
          "offset": "0",
          "source": "seeded",
          "warning": "Rows are seeded demonstration data.",
          "filters": {
            "project_numbers": ["001"],
            "environments": ["dev"],
            "models": ["gpt-4o"],
            "categories": ["Coding"],
            "success_values": [true, false]
          },
          "summary": {
            "source": "seeded",
            "record_count": 1,
            "success_count": "1",
            "error_count": 0,
            "input_tokens": 120,
            "cached_input_tokens": "20",
            "output_tokens": 30,
            "models": ["gpt-4o"],
            "categories": ["Coding"]
          }
        }
        """;

        var result = JsonSerializer.Deserialize<OperationsPromptSearchResult>(
            json,
            JsonOptions);

        Assert.NotNull(result);
        Assert.Equal("Rows are seeded demonstration data.", result.Warning);
        Assert.Equal(120, result.Rows.Single().InputTokens);
        Assert.Equal(20, result.Rows.Single().CachedInputTokens);
        Assert.Equal(425.5, result.Rows.Single().LatencyMilliseconds);
        Assert.Equal(["001"], result.Filters.ProjectNumbers);
        Assert.Equal([true, false], result.Filters.SuccessValues);
        Assert.Equal(1, result.Summary.SuccessCount);
    }

    [Fact]
    public void Models_NormalizeNullCollectionsAndObjects()
    {
        const string overviewJson = """
        {
          "factory": null,
          "regions": null,
          "projects": null,
          "common_resource_groups": null,
          "resource_inventory": null,
          "monitoring": null,
          "operation_configs": null,
          "factory_action_requests": null,
          "prompt_summary": null
        }
        """;
        const string promptsJson = """
        {"rows":null,"filters":null,"summary":null}
        """;

        var overview = JsonSerializer.Deserialize<OperationsOverview>(
            overviewJson,
            JsonOptions)!;
        var prompts = JsonSerializer.Deserialize<OperationsPromptSearchResult>(
            promptsJson,
            JsonOptions)!;

        Assert.Empty(overview.Regions);
        Assert.Empty(overview.Projects);
        Assert.Empty(overview.Factory.Subscriptions);
        Assert.Empty(overview.ResourceInventory.Resources);
        Assert.Empty(overview.Monitoring.TokensOverTime.Labels);
        Assert.Empty(overview.OperationConfigs);
        Assert.Empty(overview.FactoryActionRequests);
        Assert.Empty(overview.PromptSummary.Models);
        Assert.Empty(prompts.Rows);
        Assert.Empty(prompts.Filters.Models);
        Assert.Empty(prompts.Summary.Categories);
    }

    [Fact]
    public void ConfigAndDraftActions_DeserializeExactResponseShapes()
    {
        const string configJson = """
        {
          "aifactory_folder": "C:\\factory",
          "project_number": "001",
          "environment": "prod",
          "kind": "finetuning",
          "config": {"training_type": "SFT"},
          "is_saved": "true",
          "updated_at": null
        }
        """;
        const string factoryActionJson = """
        {
          "request_id": "factory-1",
          "aifactory_folder": "C:\\factory",
          "action": "clone",
          "target_region": "westeurope",
          "source_region": "swedencentral",
          "status": "draft",
          "created_at": "2026-09-05T15:00:00Z",
          "message": "Draft only; no Azure resources were changed."
        }
        """;
        const string projectActionJson = """
        {
          "request_id": "project-1",
          "aifactory_folder": "C:\\factory",
          "action": "promote",
          "target_region": "stage",
          "source_region": "dev",
          "status": "draft",
          "created_at": "2026-09-05T15:00:00Z",
          "message": "Draft only; no Azure resources were changed.",
          "request_type": "project",
          "project_number": "001",
          "source_environment": "dev",
          "target_environment": "stage"
        }
        """;

        var config = JsonSerializer.Deserialize<OperationConfigResult>(
            configJson,
            JsonOptions)!;
        var factoryAction = JsonSerializer.Deserialize<DraftFactoryAction>(
            factoryActionJson,
            JsonOptions)!;
        var projectAction = JsonSerializer.Deserialize<DraftProjectAction>(
            projectActionJson,
            JsonOptions)!;

        Assert.True(config.IsSaved);
        Assert.Equal("SFT", config.Config["training_type"]!.GetValue<string>());
        Assert.Equal("swedencentral", factoryAction.SourceRegion);
        Assert.Equal("project", projectAction.RequestType);
        Assert.Equal("stage", projectAction.TargetEnvironment);
    }
}
