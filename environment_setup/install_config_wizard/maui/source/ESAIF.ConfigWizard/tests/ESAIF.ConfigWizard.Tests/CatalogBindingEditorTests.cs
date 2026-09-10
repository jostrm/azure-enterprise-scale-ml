using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class CatalogBindingEditorTests
{
    private const string Root = @"C:\catalog";
    private const string Subscription = "11111111-1111-4111-8111-111111111111";
    private static readonly CatalogScaleSet Selected = new()
    {
        Id = "scale-selected", Environment = "dev", Suffix = "001",
        SubscriptionId = Subscription, TenantId = "22222222-2222-4222-8222-222222222222", Orchestrator = "gha"
    };
    private static CatalogRuntimeBinding Binding() => new()
    {
        ContractVersion = 1, Orchestrator = "gha", WriterId = "writer-one",
        Repository = "https://github.com/customer/repository", Ref = "refs/heads/main", SharedRemote = true,
        AuthNamespace = "customer-one", DeploymentObjectId = "33333333-3333-4333-8333-333333333333",
        Locks = new() { AccountUrl = "https://lockaccount.blob.core.windows.net", Container = "factory-locks",
            CoordinationBlob = "coordination/v1.json", CoordinationHash = new string('a', 64), Revision = 2 },
        Targets =
        [
            new() { ScaleSetId = Selected.Id, ResourceGroupIds = [Group("selected")], CommonDependencyIds = [Group("common")] },
            new() { ScaleSetId = "other-scale", ResourceGroupIds = [Group("keep-other")], CommonDependencyIds = [Group("keep-dependency")] }
        ]
    };
    private static CatalogFactory Factory(CatalogRuntimeBinding? binding = null) => new()
    {
        Id = "factory-a", Key = "mrvel-sdc", Prefix = "mrvel", Region = "swedencentral",
        ScaleSets = [Selected, Selected with { Id = "other-scale", Suffix = "002" }],
        Bindings = [new() { Orchestrator = "gha", Configuration = binding ?? Binding(), Verified = false }]
    };
    private static string Group(string name) => $"/subscriptions/{Subscription}/resourceGroups/{name}";

    private static CatalogTargetExecution Execution(string writer) => new()
    {
        WriterId = writer, AuthNamespace = writer + "-namespace",
        DeploymentObjectId = "44444444-4444-4444-8444-444444444444",
        Runner = new() { Kind = "hosted", Os = "linux", Image = "ubuntu-24.04" }
    };

    [Fact]
    public void TargetExecutionRoundTripsWhileUnrelatedScopesAreEdited()
    {
        var binding = Binding();
        binding = binding with { Targets = binding.Targets.Select((target, index) =>
            target with { Execution = Execution("writer-" + index) }).ToArray() };
        var factory = Factory(binding);
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        Assert.True(editor.UseTargetExecution);
        Assert.True(CatalogBindingEditor.Equivalent(binding, editor.Build(Root, factory, Selected)));
        editor.ResourceGroupIds = Group("changed");
        var actual = editor.Build(Root, factory, Selected);
        Assert.Equal(binding.Targets[0].Execution, actual.Targets[0].Execution);
        Assert.Same(binding.Targets[1], actual.Targets[1]);
        var details = FactoryCatalogPresentation.BindingDetails(actual);
        Assert.Contains("Scale-set execution override:", details);
        Assert.Contains("writer-0-namespace", details);
        Assert.Contains("writer-1-namespace", details);
        Assert.Contains("Ubuntu", editor.TargetRunner.Image!.Display);
    }

    [Fact]
    public void TargetOverridesRequireSharedRemoteWholeIdentityAndExplicitRunner()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.UseTargetExecution = true;
        editor.SharedRemote = false;
        Assert.Contains("shared remote", Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected)).Message);
        editor.SharedRemote = true;
        editor.TargetWriterId = "dev001-writer";
        editor.TargetAuthNamespace = "dev001-auth";
        editor.TargetDeploymentObjectId = Execution("dev001").DeploymentObjectId;
        Assert.Contains("Linux runner", Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected)).Message);
        editor.TargetRunner.Choice = editor.TargetRunner.Choices.Single(choice => choice.Value == "hosted");
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
        editor.TargetRunner.Image = editor.TargetRunner.Images.Single(choice => choice.Value == "ubuntu-22.04");
        Assert.Equal("dev001-writer", editor.Build(Root, factory, Selected).Targets[0].Execution!.WriterId);
        editor.TargetAuthNamespace = string.Empty;
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
    }

    [Theory]
    [InlineData("gha")]
    [InlineData("ado")]
    public void TargetSelfHostedRunnerPreservesProviderSpecificFields(string route)
    {
        var scale = Selected with { Orchestrator = route };
        var execution = Execution("target") with { Runner = route == "gha"
            ? new() { Kind = "self-hosted", Os = "linux", Labels = ["self-hosted", "linux", "Dev 001"] }
            : new() { Kind = "self-hosted", Os = "linux", Pool = "Linux Pool", AgentName = "Dev 001" } };
        var binding = Binding() with { Orchestrator = route,
            Repository = route == "gha" ? "https://github.com/customer/repository" : "https://dev.azure.com/customer/project/_git/repository" };
        binding = binding with { Targets = binding.Targets.Select(target => target with { Execution = execution }).ToArray() };
        var factory = Factory() with { ScaleSets = [scale],
            Bindings = [new() { Orchestrator = route, Configuration = binding }] };
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, scale);
        var actual = editor.Build(Root, factory, scale);
        Assert.True(CatalogBindingEditor.Equivalent(binding, actual));
        Assert.Equal(route == "gha", editor.TargetRunner.ShowsGithub);
        Assert.Equal(route == "ado", editor.TargetRunner.ShowsAdo);
        var edits = 0;
        editor.Edited += (_, _) => edits++;
        if (route == "gha") editor.TargetRunner.Labels += "\nnew-label";
        else editor.TargetRunner.AgentName = "Other agent";
        Assert.True(editor.IsDirty);
        Assert.Equal(1, edits);
        Assert.False(CatalogBindingEditor.Equivalent(binding, editor.Build(Root, factory, scale)));
    }

    [Fact]
    public void TargetExecutionChangesParticipateInConflictDetectionAndEchoValidation()
    {
        var binding = Binding();
        binding = binding with { Targets = binding.Targets.Select(target => target with { Execution = Execution("old") }).ToArray() };
        var factory = Factory(binding);
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.TargetWriterId = "unsaved";
        var changed = binding with { Targets = binding.Targets.Select(target => target with { Execution = Execution("other") }).ToArray() };
        Assert.False(CatalogBindingEditor.Equivalent(binding, changed));
        editor.LoadScope(Root, Factory(changed), Selected);
        Assert.True(editor.HasConflict);
        Assert.Equal("unsaved", editor.TargetWriterId);
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, Factory(changed), Selected));
    }

    [Fact]
    public void DisablingTargetOverrideOnlyRemovesExplicitlySelectedTargetExecution()
    {
        var binding = Binding();
        binding = binding with { Targets = binding.Targets.Select(target => target with { Execution = Execution("saved") }).ToArray() };
        var factory = Factory(binding);
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.UseTargetExecution = false;
        var actual = editor.Build(Root, factory, Selected);
        Assert.Null(actual.Targets[0].Execution);
        Assert.Same(binding.Targets[1].Execution, actual.Targets[1].Execution);
    }

    [Fact]
    public void TypedEditsPreserveAllOtherScaleSetTargetsAndRawValues()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.ResourceGroupIds = Group("edited-exact-group");
        var edited = editor.Build(Root, factory, Selected);
        Assert.Equal(2, edited.Targets.Count);
        Assert.Equal(Group("edited-exact-group"), Assert.Single(edited.Targets[0].ResourceGroupIds));
        Assert.Same(factory.Bindings[0].Configuration!.Targets[1], edited.Targets[1]);
        Assert.Equal("refs/heads/main", edited.Ref);
        Assert.Equal(factory.Bindings[0].Configuration!.Locks, edited.Locks);
        Assert.Null(edited.Runner);
        Assert.Equal(Group("selected"), Assert.Single(factory.Bindings[0].Configuration!.Targets[0].ResourceGroupIds));
    }

    [Fact]
    public void ChangedSavedBindingKeepsDirtyInputButBlocksStaleReplacement()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.WriterId = "unsaved-writer";
        var changed = Factory(Binding() with { Ref = "refs/heads/other" });
        editor.LoadScope(Root, changed, Selected);
        Assert.Equal("unsaved-writer", editor.WriterId);
        Assert.True(editor.HasConflict);
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, changed, Selected));
        editor.LoadScope(Root, changed, Selected, discardEdits: true);
        Assert.False(editor.HasConflict);
        Assert.False(editor.IsDirty);
        Assert.Equal("refs/heads/other", editor.ConsumerRef);
        Assert.Equal("writer-one", editor.WriterId);
    }

    [Fact]
    public void DifferentRootOrScaleCannotReuseBindingDraft()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        Assert.Throws<InvalidOperationException>(() => editor.Build(@"C:\other", factory, Selected));
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, factory.ScaleSets[1]));
    }

    [Fact]
    public void WritableScopeMustMatchExactSelectedSubscription()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.ResourceGroupIds = Group("wrong").Replace(Subscription, "99999999-9999-4999-8999-999999999999");
        Assert.Contains("exact subscription", Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected)).Message);
    }

    [Theory]
    [InlineData("/subscriptions/*/resourceGroups/selected")]
    [InlineData("selected")]
    [InlineData("/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/*")]
    public void ScopeFiltersAreNotAcceptedAsResourceAuthority(string value)
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.ResourceGroupIds = value;
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
    }

    [Fact]
    public void RuntimeEnrollmentRequiresNamespaceAndObjectIdTogether()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.DeploymentObjectId = string.Empty;
        Assert.Contains("both authentication namespace", Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected)).Message);
    }

    [Fact]
    public void EntireBindingIsIncludedInDeliberateReviewWithoutRawJson()
    {
        var details = FactoryCatalogPresentation.BindingDetails(Binding());
        Assert.Contains("keep-other", details);
        Assert.Contains("keep-dependency", details);
        Assert.Contains("Coordination hash: " + new string('a', 64), details);
        Assert.Contains("Deployment object ID:", details);
        Assert.DoesNotContain("CatalogRuntimeBinding {", details);
    }

    [Fact]
    public void UnreadableBindingRequiresExplicitWholeBindingReplacement()
    {
        var factory = Factory() with
        {
            Bindings = [new() { Orchestrator = "gha", Error = "Unreadable binding", Configuration = null }]
        };
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        Assert.True(editor.IsUnreadable);
        Assert.Contains("acknowledge", Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected)).Message);
    }

    [Fact]
    public void CatalogTemplatesHaveSingleRootsAndUseTypedBindingInputs()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Assets", "Disclosure", "FactoryCatalogPage.xaml");
        var document = System.Xml.Linq.XDocument.Load(path);
        foreach (var template in document.Descendants().Where(element => element.Name.LocalName == "DataTemplate"))
            Assert.Single(template.Elements());
        Assert.Contains(document.Descendants(), element => (string?)element.Attribute("Text") == "{Binding BindingEditor.CoordinationHash}");
        Assert.DoesNotContain(document.Descendants(), element => element.Name.LocalName == "Editor");
    }

    [Theory]
    [InlineData("ubuntu-latest")]
    [InlineData("ubuntu-24.04")]
    [InlineData("ubuntu-22.04")]
    public void HostedRunnerRequiresExplicitLinuxImageAndRoundTrips(string image)
    {
        var runner = new CatalogRunnerSelection { Kind = "hosted", Os = "linux", Image = image };
        var binding = Binding() with { Runner = runner };
        var factory = Factory(binding);
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        var actual = editor.Build(Root, factory, Selected);
        Assert.True(CatalogBindingEditor.Equivalent(binding, actual));
        Assert.Equal(runner, actual.Runner);
        Assert.Null(actual.Runner!.Labels);
        Assert.Null(actual.Runner.Pool);
    }

    [Fact]
    public void HostedRunnerDoesNotInferImageOrAcceptWindows()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.RunnerChoice = editor.RunnerChoices.Single(x => x.Value == "hosted");
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
        editor.RunnerImage = new("windows-latest", "Windows");
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
    }

    [Fact]
    public void GithubSelfHostedLabelsStayExactAndDoNotBecomeAdoFields()
    {
        var binding = Binding() with
        {
            Runner = new() { Kind = "self-hosted", Os = "linux", Labels = ["self-hosted", "linux", "Customer Build"] }
        };
        var factory = Factory(binding);
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        Assert.True(editor.ShowsGithubRunner);
        var actual = editor.Build(Root, factory, Selected);
        Assert.True(CatalogBindingEditor.Equivalent(binding, actual));
        Assert.Equal(new[] { "self-hosted", "linux", "Customer Build" }, actual.Runner!.Labels);
        Assert.Null(actual.Runner.Image);
        Assert.Null(actual.Runner.Pool);
        Assert.Null(actual.Runner.AgentName);
        editor.RunnerLabels = "self-hosted\nCustomer Build";
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
    }

    [Fact]
    public void AdoSelfHostedPoolAndOptionalAgentRoundTripWithoutGithubLabels()
    {
        var scale = Selected with { Orchestrator = "ado" };
        var binding = Binding() with
        {
            Orchestrator = "ado", Repository = "https://dev.azure.com/customer/project/_git/config",
            Runner = new() { Kind = "self-hosted", Os = "linux", Pool = "Linux Pool", AgentName = "agent-01" }
        };
        var factory = Factory(binding) with { ScaleSets = [scale, scale with { Id = "other-scale", Suffix = "002" }] };
        factory = factory with { Bindings = [new() { Orchestrator = "ado", Configuration = binding }] };
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, scale);
        Assert.True(editor.ShowsAdoRunner);
        var actual = editor.Build(Root, factory, scale);
        Assert.Equal("Linux Pool", actual.Runner!.Pool);
        Assert.Equal("agent-01", actual.Runner.AgentName);
        Assert.Null(actual.Runner.Labels);
        Assert.Null(actual.Runner.Image);
        Assert.Equal(2, actual.Targets.Count);
        editor.RunnerPool = string.Empty;
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, scale));
    }

    [Fact]
    public void ExplicitRunnerRequiresNamespacedIdentityAndParticipatesInEchoValidation()
    {
        var factory = Factory();
        var editor = new CatalogBindingEditor();
        editor.LoadScope(Root, factory, Selected);
        editor.RunnerChoice = editor.RunnerChoices.Single(x => x.Value == "hosted");
        editor.RunnerImage = editor.HostedImages[0];
        var withRunner = editor.Build(Root, factory, Selected);
        Assert.False(CatalogBindingEditor.Equivalent(Binding(), withRunner));
        editor.AuthNamespace = editor.DeploymentObjectId = string.Empty;
        Assert.Throws<InvalidOperationException>(() => editor.Build(Root, factory, Selected));
    }
}
