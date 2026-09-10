using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class FactoryConfigurationViewModelTests
{
    private static FactorySchema Schema => new()
    {
        Defaults = new JsonObject { ["admin_location"] = "swedencentral", ["admin_aifactorySuffixRG"] = "-001" },
        Sections = new SchemaSections { ScaleSetVariables = ["admin_location", "admin_aifactorySuffixRG"] }
    };

    [Fact]
    public async Task PrepareAndEdit_AreIndependentOfSourceAndDoNotWriteUntilSave()
    {
        var client = new StubClient();
        var vm = new FactoryConfigurationViewModel(client);
        await vm.PrepareAsync("clone", "norwayeast", @"C:\source", Schema);
        Assert.True(vm.CanSave);
        Assert.Single(vm.Fields);
        Assert.Equal("Clone AI Factory", vm.Title);
        Assert.Empty(vm.DestinationFolder);
        vm.Fields[0].Value = "-002";
        Assert.Empty(client.Prepared.State["admin_aifactorySuffixRG"]!.GetValue<string>());
        Assert.Equal(0, client.SaveCalls);
        vm.DestinationFolder = @"C:\target";
        await vm.SaveAsync();
        Assert.True(vm.IsSaved);
        Assert.False(vm.CanSave);
        Assert.False(vm.CanEdit);
        Assert.Equal("-002", client.SavedState!["admin_aifactorySuffixRG"]!.GetValue<string>());
        Assert.Equal("norwayeast", client.SavedState["admin_location"]!.GetValue<string>());
        Assert.Equal(@"C:\target", client.Destination);
    }

    [Fact]
    public async Task SaveFailure_RetainsEditableFormAndExplainsError()
    {
        var client = new StubClient { SaveError = new HttpRequestException("Destination already exists.") };
        var vm = new FactoryConfigurationViewModel(client);
        await vm.PrepareAsync("factory", "norwayeast", null, Schema);
        vm.DestinationFolder = @"C:\target";
        await vm.SaveAsync();
        Assert.False(vm.IsSaved);
        Assert.True(vm.CanSave);
        Assert.Contains("already exists", vm.StatusMessage);
    }

    [Fact]
    public async Task MissingDestination_DoesNotSendSave()
    {
        var client = new StubClient();
        var vm = new FactoryConfigurationViewModel(client);
        await vm.PrepareAsync("factory", "norwayeast", null, Schema);
        await vm.SaveAsync();
        Assert.Equal(0, client.SaveCalls);
        Assert.Contains("destination", vm.StatusMessage);
    }

    [Fact]
    public async Task ScaleSet_PreselectsExistingFolderAndSavedStateIsIndependent()
    {
        var client = new StubClient();
        var vm = new FactoryConfigurationViewModel(client);
        await vm.PrepareAsync("scale-set", "norwayeast", @"C:\source", Schema);
        Assert.True(vm.IsScaleSet);
        Assert.False(vm.IsNewFolder);
        Assert.Equal(@"C:\source", vm.DestinationFolder);
        await vm.SaveAsync();
        vm.GetSavedState()["admin_location"] = "changed";
        Assert.Equal("norwayeast", vm.GetSavedState()["admin_location"]!.GetValue<string>());
    }

    [Fact]
    public async Task UnknownApiField_PreventsSavingIncompleteConfiguration()
    {
        var client = new StubClient
        {
            Prepared = new FactoryConfigurationPreparation { FieldKeys = ["unknown_setting"] }
        };
        var vm = new FactoryConfigurationViewModel(client);
        await vm.PrepareAsync("factory", "norwayeast", null, Schema);
        Assert.False(vm.CanSave);
        Assert.Contains("unknown setup field", vm.StatusMessage);
    }

    [Fact]
    public async Task UnsupportedFoundryHubIsHiddenButPreservedInSavedState()
    {
        var client = new StubClient
        {
            Prepared = new FactoryConfigurationPreparation
            {
                State = new JsonObject { ["admin_location"] = "norwayeast", ["addAIFoundryHub"] = "false" },
                FieldKeys = ["admin_location", "addAIFoundryHub"]
            }
        };
        var vm = new FactoryConfigurationViewModel(client);
        await vm.PrepareAsync("factory", "norwayeast", null, Schema);
        Assert.True(vm.CanSave);
        Assert.Empty(vm.Fields);
        vm.DestinationFolder = @"C:\target";
        await vm.SaveAsync();
        Assert.Equal("false", client.SavedState!["addAIFoundryHub"]!.GetValue<string>());
    }

    private sealed class StubClient : IFactoryConfigurationClient
    {
        public FactoryConfigurationPreparation Prepared { get; init; } = new()
        {
            State = new JsonObject { ["admin_location"] = "norwayeast", ["admin_aifactorySuffixRG"] = "" },
            FieldKeys = ["admin_location", "admin_aifactorySuffixRG"], Message = "Review configuration."
        };
        public int SaveCalls { get; private set; }
        public Exception? SaveError { get; init; }
        public JsonObject? SavedState { get; private set; }
        public string? Destination { get; private set; }

        public Task<FactoryConfigurationPreparation> PrepareFactoryConfigurationAsync(
            string kind, string targetRegion, string? sourceFolder = null, CancellationToken cancellationToken = default) =>
            Task.FromResult(Prepared);

        public Task<FactoryConfigurationSaveResult> SaveFactoryConfigurationAsync(
            string kind, string targetRegion, string? sourceFolder, string destinationFolder,
            JsonObject state, CancellationToken cancellationToken = default)
        {
            SaveCalls++;
            SavedState = state;
            Destination = destinationFolder;
            return SaveError is not null ? Task.FromException<FactoryConfigurationSaveResult>(SaveError)
                : Task.FromResult(new FactoryConfigurationSaveResult { State = state, Path = "new.json", Message = "Saved. Azure unchanged." });
        }
    }
}
