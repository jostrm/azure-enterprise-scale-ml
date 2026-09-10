using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class SavedConfigurationVerifierTests
{
    private const string Folder = @"C:\factory";
    private const string Sub = "11111111-1111-4111-8111-111111111111";
    private static ProjectDeploymentScope Scope => new()
    {
        PrefixResourceGroup = "demo-", SuffixResourceGroup = "-007", Region = "swedencentral", SubscriptionIds = [Sub]
    };
    private static OperationsOverview Overview => new()
    {
        Factory = new FactorySummary
        {
            Folder = Folder, PrefixResourceGroup = "demo-", SuffixResourceGroup = "-007", MonitoringRegions = ["swedencentral"]
        },
        ResourceInventory = new ResourceInventorySummary { Source = "azure", IsComplete = true, Subscriptions = [Sub] },
        Projects = [new()
        {
            ProjectNumber = "017",
            Environments = [new() { ResourceGroup = "demo-project017-sdc-dev-007", SubscriptionId = Sub }]
        }],
        CommonResourceGroups = [new()
        {
            Name = "demo-esml-common-sdc-dev-007", SubscriptionId = Sub
        }]
    };

    private static SavedConfigurationItemViewModel ProjectItem()
    {
        var item = new SavedConfigurationItemViewModel(new ProjectSummary
        {
            ProjectNumber = "017", Path = @"C:\factory\project-017\project_state.json", DeploymentScope = Scope
        }, Folder);
        item.UpdateDeployment(Overview);
        return item;
    }

    private static SavedConfigurationItemViewModel ScaleSetItem()
    {
        var item = new SavedConfigurationItemViewModel(new ScaleSetSummary
        {
            ScaleSetId = "007", Path = @"C:\factory\scaleset_007.json", DeploymentScope = Scope
        }, Folder);
        item.UpdateDeployment(Overview);
        return item;
    }

    private static ProjectResourceGroupVerification ProjectResult(SavedConfigurationItemViewModel item, int code = 200) => new()
    {
        ProjectNumber = "017", CheckedAt = "2026-09-08T10:00:00Z", Message = "Checked",
        Checks = [new() { ResourceId = item.ResourceGroupLinks[0].ResourceId, HttpStatus = code, Verified = code == 200 }]
    };

    [Fact]
    public async Task ProjectAndScaleSetBothRequireRealVerificationAndUseAccessibleLabel()
    {
        var project = ProjectItem();
        var scale = ScaleSetItem();
        var client = new StubClient
        {
            Project = ProjectResult(project),
            ScaleSet = new()
            {
                ScaleSetId = "007", CheckedAt = "2026-09-08T10:00:00Z",
                Checks = [new() { ResourceId = scale.ResourceGroupLinks[0].ResourceId, HttpStatus = 200, Verified = true }]
            }
        };
        Assert.False(project.IsResourceGroupVerified); // Azure inventory is not HTTP proof.
        var verifier = new SavedConfigurationVerifier(client, client);
        Assert.True(await verifier.VerifyAsync(new[] { project, scale }, () => Folder));
        Assert.Equal(1, client.ProjectRequests);
        Assert.Equal(1, client.ScaleSetRequests);
        foreach (var item in new[] { project, scale })
        {
            Assert.True(item.IsResourceGroupVerified);
            Assert.Equal("Accessible", item.VerificationLabel);
            Assert.DoesNotContain("200", item.VerificationLabel);
            Assert.Contains("HTTP 200", item.VerificationDetails);
        }
    }

    [Fact]
    public async Task FailedProjectAccessStaysUnlitAndReportsCode()
    {
        var item = ProjectItem();
        var client = new StubClient { Project = ProjectResult(item, 403) };
        await new SavedConfigurationVerifier(client, client).VerifyAsync(new[] { item }, () => Folder);
        Assert.False(item.IsResourceGroupVerified);
        Assert.Equal("Not verified", item.VerificationLabel);
        Assert.Contains("HTTP 403", item.VerificationDetails);
    }

    [Fact]
    public async Task NoResourceGroupDoesNotIssueAnArbitraryRequest()
    {
        var item = ProjectItem();
        item.UpdateDeployment(Overview with { Projects = [] });
        var client = new StubClient();
        await new SavedConfigurationVerifier(client, client).VerifyAsync(new[] { item }, () => Folder);
        Assert.Equal(0, client.ProjectRequests);
        Assert.False(item.IsResourceGroupVerified);
        Assert.Equal("Not deployed", item.VerificationLabel);
    }

    [Fact]
    public async Task ChangingFolderOrRemovingItemDuringRequestRejectsOldSuccess()
    {
        foreach (var removeItem in new[] { false, true })
        {
            var item = ProjectItem();
            var release = new TaskCompletionSource<ProjectResourceGroupVerification>();
            var client = new StubClient { PendingProject = release.Task };
            var items = new List<SavedConfigurationItemViewModel> { item };
            var folder = Folder;
            var pending = new SavedConfigurationVerifier(client, client).VerifyAsync(items, () => folder);
            if (removeItem)
            {
                items.Remove(item);
            }
            else
            {
                folder = @"C:\other";
            }
            release.SetResult(ProjectResult(item));
            await pending;
            Assert.False(item.IsResourceGroupVerified);
        }
    }

    [Fact]
    public async Task ANewVerificationCancelsEarlierResultsEvenIfServerIgnoresCancellation()
    {
        var item = ProjectItem();
        var release = new TaskCompletionSource<ProjectResourceGroupVerification>();
        var client = new StubClient { PendingProject = release.Task, Project = ProjectResult(item, 404) };
        var verifier = new SavedConfigurationVerifier(client, client);
        var pending = verifier.VerifyAsync(new[] { item }, () => Folder);
        client.PendingProject = null;
        await verifier.VerifyAsync(new[] { item }, () => Folder);
        release.SetResult(ProjectResult(item));
        await pending;
        Assert.False(item.IsResourceGroupVerified);
        Assert.Contains("HTTP 404", item.VerificationDetails);
    }

    [Fact]
    public async Task RequestFailureDoesNotLeaveEarlierBlueState()
    {
        var item = ProjectItem();
        item.ApplyVerification(ProjectResult(item));
        var client = new StubClient { Failure = new HttpRequestException("Timed out") };
        await new SavedConfigurationVerifier(client, client).VerifyAsync(new[] { item }, () => Folder);
        Assert.False(item.IsResourceGroupVerified);
        Assert.Contains("Timed out", item.VerificationDetails);
    }

    [Fact]
    public void WrongProjectSuccessfulResponseDoesNotLightTheSelectedConfiguration()
    {
        var item = ProjectItem();
        item.ApplyVerification(ProjectResult(item) with { ProjectNumber = "018" });
        Assert.False(item.IsResourceGroupVerified);
    }

    private sealed class StubClient : IProjectVerificationClient, IScaleSetVerificationClient
    {
        public int ProjectRequests { get; private set; }
        public int ScaleSetRequests { get; private set; }
        public ProjectResourceGroupVerification Project { get; init; } = new();
        public ScaleSetResourceGroupVerification ScaleSet { get; init; } = new();
        public Task<ProjectResourceGroupVerification>? PendingProject { get; set; }
        public Exception? Failure { get; init; }

        public Task<ProjectResourceGroupVerification> VerifyProjectResourceGroupsAsync(
            string folder, string number, string path, CancellationToken cancellationToken = default)
        {
            ProjectRequests++;
            Assert.Equal(Folder, folder);
            Assert.Equal("017", number);
            Assert.Equal(@"C:\factory\project-017\project_state.json", path);
            return Failure is not null ? Task.FromException<ProjectResourceGroupVerification>(Failure)
                : PendingProject ?? Task.FromResult(Project);
        }

        public Task<ScaleSetResourceGroupVerification> VerifyScaleSetResourceGroupsAsync(
            string folder, string id, string path, CancellationToken cancellationToken = default)
        {
            ScaleSetRequests++;
            return Task.FromResult(ScaleSet);
        }
    }
}
