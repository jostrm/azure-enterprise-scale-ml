using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class WizardPageRebindingTests
{
    [Fact]
    public async Task RecreatedPageNullPickerSelectionCannotClearLoadedProjectOrShowConnectionPrompt()
    {
        var (vm, session) = await Create();
        session.ReplaceState(new JsonObject
        {
            ["orchestrator"] = "gha", ["project_number_000"] = "017", ["tenantId"] = "loaded-tenant",
            ["_save_folder"] = @"C:\LoadedFactory", ["common_vnet_cidr"] = "172.16.XX.0/18"
        });
        var selected = vm.CurrentStep;
        var fields = vm.VisibleFields.ToArray();
        var before = session.State.ToJsonString();
        vm.CurrentStep = null;
        await vm.InitializeAsync();
        Assert.Same(selected, vm.CurrentStep);
        Assert.Equal(fields, vm.VisibleFields);
        Assert.True(vm.HasFields);
        Assert.Equal("Start & destination", vm.CurrentTitle);
        Assert.DoesNotContain("Open Connection", vm.CurrentDescription);
        Assert.Equal("017", vm.Identity.ProjectNumber);
        Assert.Equal(before, session.State.ToJsonString());
        Assert.Equal("GitHub", vm.VisibleFields.Single(field => field.Key == "orchestrator").SelectedDisplayOption);
    }

    [Fact]
    public async Task ProjectReplacementImmediatelyRefreshesActiveSectionAndIgnoresStaleStepCallback()
    {
        var (vm, session) = await Create();
        vm.CurrentStep = vm.Steps.Single(step => step.Title == "Security & governance");
        var previous = vm.CurrentStep;
        session.ReplaceState(new JsonObject { ["tenantId"] = "new-project-tenant", ["project_number_000"] = "011" });
        Assert.NotSame(previous, vm.CurrentStep);
        var current = vm.CurrentStep;
        vm.CurrentStep = previous;
        vm.CurrentStep = null;
        Assert.Same(current, vm.CurrentStep);
        Assert.Equal("Security & governance", vm.CurrentTitle);
        Assert.Equal("new-project-tenant", vm.VisibleFields.Single(field => field.Key == "tenantId").Value);
        Assert.Equal("011", vm.Identity.ProjectNumber);
    }

    private static async Task<(WizardViewModel Model, WizardSession Session)> Create()
    {
        var api = new AiFactoryApiClient(new Transport(), new Connection());
        var session = new WizardSession(api, startupFolder: "");
        var vm = new WizardViewModel(api, new FolderPicker(), new Files(), new RecentProjectLoader(api), session);
        await vm.InitializeAsync();
        return (vm, session);
    }

    private sealed class Connection : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection("http://localhost:8765", "test-key"));
    }

    private sealed class Transport : IJsonApiTransport
    {
        public Task<T> SendAsync<T>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            object result = request.RequestUri!.AbsolutePath == "/health"
                ? new HealthStatus { Version = "test", Status = "ok" }
                : new FactorySchema
                {
                    Defaults = new JsonObject
                    {
                        ["orchestrator"] = "ado", ["project_number_000"] = "001",
                        ["tenantId"] = "default-tenant", ["common_vnet_cidr"] = "172.16.XX.0/18"
                    },
                    Orchestrators = ["ado", "gha"]
                };
            return Task.FromResult((T)result);
        }
    }

    private sealed class FolderPicker : IAiFactoryFolderPickerService
    {
        public Task<string?> PickFolderAsync(string currentFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }

    private sealed class Files : IConfigurationFileService
    {
        public Task<PickedConfigurationFile?> PickAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<string> SaveExportAsync(string format, string content, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }
}
