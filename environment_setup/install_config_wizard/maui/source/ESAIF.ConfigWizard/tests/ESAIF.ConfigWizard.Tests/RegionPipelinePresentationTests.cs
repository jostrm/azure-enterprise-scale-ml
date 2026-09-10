using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class RegionPipelinePresentationTests
{
    private static AzureRegionInfo FailedRegion => new()
    {
        Name = "eastus2", DisplayName = "East US 2", HasFactory = true,
        PipelineFindings =
        [
            new RegionPipelineFinding
            {
                Kind = "capacity", Service = "Azure AI Search", Status = "failed",
                Skus = ["basic", "standard", "standard2"], Source = "user_reported",
                Message = "These three SKUs could not be provisioned during the last reported run.",
                RecordedAt = "2026-09-07T15:24:13Z"
            }
        ]
    };

    [Fact]
    public void FailureStaysRedWhenSelectedAndOverridesConfiguredGreen()
    {
        Assert.Equal(RegionPipelinePresentation.FailureColor, RegionPipelinePresentation.LightColor(FailedRegion, false));
        Assert.Equal(RegionPipelinePresentation.FailureColor, RegionPipelinePresentation.LightColor(FailedRegion, true));
        Assert.True(RegionPipelinePresentation.HasFailure(FailedRegion with { HasFactory = false }));
    }

    [Fact]
    public void HoverAndSelectionExplainAllSkusWithoutInventingRunDateOrLiveHealth()
    {
        var text = RegionPipelinePresentation.Details(FailedRegion);
        Assert.Contains("basic, standard, standard2", text);
        Assert.Contains("User-reported", text);
        Assert.Contains("Run ID: not provided", text);
        Assert.Contains("Run time: not provided", text);
        Assert.Contains("not live Azure capacity", text);
        Assert.DoesNotContain("2026-09-07", text);
        Assert.Contains(text, RegionPipelinePresentation.Tooltip(FailedRegion));
    }

    [Fact]
    public void RecordedPipelineErrorShowsActualRunMetadata()
    {
        var region = FailedRegion with
        {
            PipelineFindings =
            [
                new()
                {
                    Kind = "pipeline_error", Service = "AI Factory pipeline", Status = "failed",
                    Source = "pipeline_artifact", RunId = "42", Environment = "stage",
                    ObservedAt = "2026-09-07T10:00:00Z", Message = "Deployment failed.",
                    RunUrl = "https://dev.azure.com/example/project/_build/results?buildId=42"
                }

            ]
        };
        var text = RegionPipelinePresentation.Details(region);
        Assert.Contains("pipeline failure", text);
        Assert.Contains("Run ID: 42", text);
        Assert.Contains("2026-09-07 10:00 UTC", text);
        Assert.Contains("Environment: stage", text);
    }

    [Fact]
    public void CanonicalSearchService_HasReadableDisplayName()
    {
        var region = FailedRegion with
        {
            PipelineFindings = [FailedRegion.PipelineFindings[0] with { Service = "microsoft.search/searchservices" }]
        };
        Assert.Contains("Azure AI Search", RegionPipelinePresentation.Details(region));
        Assert.Contains("Environment: not provided", RegionPipelinePresentation.Details(region));
    }

    [Fact]
    public void ResolvedOrUnknownEvidenceDoesNotProduceRed()
    {
        var region = FailedRegion with { PipelineFindings = [FailedRegion.PipelineFindings[0] with { Status = "resolved" }] };
        Assert.False(RegionPipelinePresentation.HasFailure(region));
        Assert.Empty(RegionPipelinePresentation.Details(region));
        Assert.Equal("#61F3B1", RegionPipelinePresentation.LightColor(region, false));
        Assert.Equal("#FFD48A", RegionPipelinePresentation.LightColor(region, true));
        Assert.Equal("#79DCED", RegionPipelinePresentation.LightColor(new AzureRegionInfo(), false));
    }
}
