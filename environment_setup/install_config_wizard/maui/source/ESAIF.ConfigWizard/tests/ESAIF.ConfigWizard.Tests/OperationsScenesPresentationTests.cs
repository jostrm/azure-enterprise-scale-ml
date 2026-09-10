using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class OperationsScenesPresentationTests
{
    [Fact]
    public void Flatten_GroupsAndSortsProjectEnvironmentsNumerically()
    {
        var projects = new[]
        {
            Project("10", Environment("dev"), Environment("prod")),
            Project("2", Environment("stage"), Environment("dev")),
            Project("1", Environment("dev"))
        };

        var dev = ProjectEnvironmentCardViewModel.Flatten(projects, "dev");
        var stage = ProjectEnvironmentCardViewModel.Flatten(projects, "stage");
        var prod = ProjectEnvironmentCardViewModel.Flatten(projects, "prod");

        Assert.Equal(["1", "2", "10"], dev.Select(card => card.ProjectNumber));
        Assert.Single(stage);
        Assert.Single(prod);
        Assert.Equal(3, dev.Count);
    }

    [Theory]
    [InlineData("dev", "stage")]
    [InlineData("stage", "prod")]
    [InlineData("prod", null)]
    public void DeploymentTarget_UsesForwardEnvironmentOnly(
        string environment,
        string? target)
    {
        Assert.Equal(
            target,
            ProjectEnvironmentCardViewModel.GetDeploymentTarget(environment));
    }

    [Theory]
    [InlineData("dataops", "frequency,schedule,load_mode,source_watermark_column,late_arrival_minutes,window_type,window_size_minutes,slide_minutes,session_gap_minutes,retry_count")]
    [InlineData("mlops", "frequency,schedule,task_type,metric,threshold,promotion_environment,retrain_on_data_drift,retrain_on_concept_drift,retrain_on_model_drift,drift_threshold,minimum_samples")]
    [InlineData("rag", "frequency,schedule,index_update_mode,vector_store,embedding_model,chunk_size,chunk_overlap,retrieval_top_k,hybrid_search,semantic_reranking,freshness_threshold_hours,evaluation_metric,evaluation_threshold,promotion_environment")]
    [InlineData("finetuning", "training_type,base_model,dataset_uri,validation_split,epochs,learning_rate_multiplier,batch_size,evaluation_metric,evaluation_threshold,promotion_environment,checkpoint_strategy,responsible_ai_evaluation,estimated_training_examples")]
    public void FormFactory_UsesExactEditableFieldKeys(
        string kind,
        string expectedKeys)
    {
        var form = OperationConfigFormFactory.Create(kind, ConfigFor(kind));

        Assert.Equal(expectedKeys.Split(','), form.Fields.Select(field => field.Key));
    }

    [Fact]
    public void FormFactory_AssignsExpectedFieldTypes()
    {
        var form = OperationConfigFormFactory.Create("finetuning", ConfigFor("finetuning"));

        Assert.Equal(OperationConfigFieldType.Choice, form.Find("training_type")!.Type);
        Assert.Equal(OperationConfigFieldType.Multiline, form.Find("dataset_uri")!.Type);
        Assert.Equal(OperationConfigFieldType.Number, form.Find("epochs")!.Type);
        Assert.Equal(OperationConfigFieldType.Boolean, form.Find("responsible_ai_evaluation")!.Type);
    }

    [Fact]
    public void BuildConfig_DoesNotPersistMetadata()
    {
        var form = OperationConfigFormFactory.Create("mlops", ConfigFor("mlops"));

        Assert.True(form.TryBuildConfig(out var config, out _));
        Assert.DoesNotContain("metric_catalogs", config.Select(item => item.Key));
        Assert.DoesNotContain("drift_explanations", config.Select(item => item.Key));
    }

    [Fact]
    public void MlOps_TaskChangeUpdatesChoicesAndResetsInvalidMetric()
    {
        var form = OperationConfigFormFactory.Create("mlops", ConfigFor("mlops"));
        var task = form.Find("task_type")!;
        var metric = form.Find("metric")!;

        Assert.Equal(["accuracy", "f1_score"], metric.Choices);
        task.Value = "regression";
        Assert.Equal(["mae", "r2"], metric.Choices);
        Assert.Equal("mae", metric.Value);
        task.Value = "forecasting";
        Assert.Equal(["mape", "wape"], metric.Choices);
        Assert.Equal("mape", metric.Value);
    }

    [Fact]
    public void BuildConfig_PreservesBooleanAndNumericTypes()
    {
        var form = OperationConfigFormFactory.Create("rag", ConfigFor("rag"));
        form.Find("hybrid_search")!.BooleanValue = false;
        form.Find("chunk_size")!.Value = "2048";
        form.Find("evaluation_threshold")!.Value = "0.91";

        Assert.True(form.TryBuildConfig(out var config, out _));
        Assert.False(config["hybrid_search"]!.GetValue<bool>());
        Assert.Equal(2048L, config["chunk_size"]!.GetValue<long>());
        Assert.Equal(0.91, config["evaluation_threshold"]!.GetValue<double>(), 3);
    }

    [Fact]
    public void BuildConfig_InvalidNumberReturnsValidationMessage()
    {
        var form = OperationConfigFormFactory.Create("dataops", ConfigFor("dataops"));
        form.Find("retry_count")!.Value = "many";

        Assert.False(form.TryBuildConfig(out _, out var message));
        Assert.Contains("valid number", message);
    }

    [Theory]
    [InlineData(-180, 90, 0.04, 0.04)]
    [InlineData(180, -90, 0.96, 0.96)]
    [InlineData(0, 0, 0.5, 0.5)]
    [InlineData(1000, -1000, 0.96, 0.96)]
    public void MapCoordinates_AreBoundedAtPolesAndDateline(
        double longitude,
        double latitude,
        double expectedX,
        double expectedY)
    {
        var point = RegionMapPresentation.MapCoordinates(longitude, latitude);

        Assert.Equal(expectedX, point.X, 6);
        Assert.Equal(expectedY, point.Y, 6);
        Assert.InRange(point.X, 0, 1);
        Assert.InRange(point.Y, 0, 1);
    }

    [Fact]
    public void MapNormalizedCoordinates_MapsApiRange()
    {
        var northEast = RegionMapPresentation.MapNormalizedCoordinates(1, 1);
        var southWest = RegionMapPresentation.MapNormalizedCoordinates(-1, -1);

        Assert.Equal(0.96, northEast.X, 6);
        Assert.Equal(0.04, northEast.Y, 6);
        Assert.Equal(0.04, southWest.X, 6);
        Assert.Equal(0.96, southWest.Y, 6);
    }

    [Fact]
    public void RegionActions_DeleteOnlyActiveAndCloneUsesSelectedOrFirstActive()
    {
        var active = new AzureRegionInfo { Name = "westus", HasFactory = true };
        var inactive = new AzureRegionInfo { Name = "eastus", HasFactory = false };

        Assert.True(RegionMapPresentation.CanDelete(active));
        Assert.False(RegionMapPresentation.CanDelete(inactive));
        Assert.Equal("centralus", RegionMapPresentation.SelectCloneSource(active, ["westus", "centralus"]));
        Assert.Equal("centralus", RegionMapPresentation.SelectCloneSource(inactive, ["centralus"]));
        Assert.Null(RegionMapPresentation.SelectCloneSource(inactive, []));
        Assert.False(RegionMapPresentation.CanClone(active, ["centralus"]));
        Assert.True(RegionMapPresentation.CanClone(inactive, ["centralus"]));
    }

    private static FactoryProject Project(
        string number,
        params ProjectEnvironment[] environments) =>
        new()
        {
            ProjectNumber = number,
            DisplayName = $"Project {number}",
            Environments = environments
        };

    private static ProjectEnvironment Environment(string environment) =>
        new()
        {
            Environment = environment,
            Status = "ready",
            Region = "eastus",
            ResourceGroup = "rg",
            ResourceCount = 2
        };

    private static JsonObject ConfigFor(string kind) => kind switch
    {
        "dataops" => new JsonObject
        {
            ["frequency"] = "daily",
            ["schedule"] = "0 2 * * *",
            ["load_mode"] = "delta",
            ["source_watermark_column"] = "modified_at",
            ["late_arrival_minutes"] = 60,
            ["window_type"] = "tumbling",
            ["window_types"] = new JsonArray("sliding", "hopping", "tumbling", "session"),
            ["window_size_minutes"] = 60,
            ["slide_minutes"] = 15,
            ["session_gap_minutes"] = 30,
            ["retry_count"] = 3
        },
        "mlops" => new JsonObject
        {
            ["frequency"] = "weekly",
            ["schedule"] = "0 3 * * 1",
            ["task_type"] = "classification",
            ["metric"] = "f1_score",
            ["metric_catalogs"] = new JsonObject
            {
                ["classification"] = new JsonArray("accuracy", "f1_score"),
                ["regression"] = new JsonArray("mae", "r2"),
                ["forecasting"] = new JsonArray("mape", "wape")
            },
            ["threshold"] = 0.8,
            ["promotion_environment"] = "stage",
            ["retrain_on_data_drift"] = true,
            ["retrain_on_concept_drift"] = true,
            ["retrain_on_model_drift"] = true,
            ["drift_threshold"] = 0.15,
            ["minimum_samples"] = 1000,
            ["drift_explanations"] = new JsonObject
            {
                ["data"] = "Data drift explanation."
            }
        },
        "rag" => new JsonObject
        {
            ["frequency"] = "six_hourly",
            ["schedule"] = "0 */6 * * *",
            ["index_update_mode"] = "delta",
            ["index_update_modes"] = new JsonArray("delta", "full"),
            ["vector_store"] = "azure_ai_search",
            ["embedding_model"] = "text-embedding-3-large",
            ["chunk_size"] = 1000,
            ["chunk_overlap"] = 150,
            ["retrieval_top_k"] = 5,
            ["hybrid_search"] = true,
            ["semantic_reranking"] = true,
            ["freshness_threshold_hours"] = 24,
            ["evaluation_metric"] = "groundedness",
            ["evaluation_threshold"] = 0.8,
            ["promotion_environment"] = "stage"
        },
        "finetuning" => new JsonObject
        {
            ["training_type"] = "SFT",
            ["training_types"] = new JsonArray("SFT", "DPO", "RFT"),
            ["base_model"] = "gpt-4.1-mini",
            ["dataset_uri"] = "",
            ["validation_split"] = 0.1,
            ["epochs"] = 2,
            ["learning_rate_multiplier"] = 0.75,
            ["batch_size"] = 4,
            ["evaluation_metric"] = "validation_loss",
            ["evaluation_threshold"] = 0.8,
            ["promotion_environment"] = "stage",
            ["checkpoint_strategy"] = "best_validation",
            ["responsible_ai_evaluation"] = true,
            ["estimated_training_examples"] = 1000,
            ["training_guidance"] = new JsonObject
            {
                ["SFT"] = "Supervised fine-tuning.",
                ["baseline"] = "Evaluate the base model first."
            }
        },
        _ => throw new ArgumentOutOfRangeException(nameof(kind))
    };
}
