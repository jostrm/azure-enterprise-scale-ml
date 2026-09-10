using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using System.Text.Json.Nodes;

namespace ESAIF.ConfigWizard.Tests;

public sealed class TechnicalValuePresentationTests
{
    private const string Id = "12345678-9abc-4def-8012-123456789abc";

    [Theory]
    [InlineData("D")]
    [InlineData("N")]
    [InlineData("B")]
    [InlineData("P")]
    [InlineData("X")]
    public void EveryGuidFormatIsHiddenWithoutFragments(string format)
    {
        var raw = Guid.Parse(Id).ToString(format);
        var display = TechnicalValuePresentation.Summary(raw, "Subscription id");
        Assert.Equal("Subscription id", display);
        Assert.True(TechnicalValuePresentation.HasDetails(raw));
        Assert.DoesNotContain("12345678", display);
        Assert.Equal(Guid.Parse(Id), Guid.Parse(raw));
    }

    [Fact]
    public void MixedAndRepeatedIdsRetainEnvironmentAndReadableContext()
    {
        var raw = $"dev: {Id}\nstage: {Id}\nprod: {Id}";
        Assert.Equal("dev: [id]\nstage: [id]\nprod: [id]", TechnicalValuePresentation.Summary(raw));
        Assert.DoesNotContain("12345678", TechnicalValuePresentation.Summary(raw));
    }

    [Theory]
    [InlineData(@"C:\Users\Someone\source\my project\variables.yaml")]
    [InlineData(@"c:/Users/Someone/My Factory/variables.json")]
    [InlineData(@"\\server\share\My Factory\variables.yaml")]
    [InlineData(@"//server/share/My Factory/variables.yaml")]
    [InlineData(@"/c/Users/Someone/My Factory/scripts/deploy.sh")]
    [InlineData(@"/home/someone/My Factory/deploy.sh")]
    [InlineData(@"/Users/Someone/source/variables.yaml")]
    [InlineData(@"~/My Factory/deploy.sh")]
    [InlineData(@"./scripts/deploy.sh")]
    [InlineData(@"../My Factory/deploy.sh")]
    [InlineData(@".\My Factory\deploy.ps1")]
    [InlineData(@"..\My Factory\deploy.ps1")]
    [InlineData(@"scripts/deploy.sh")]
    [InlineData(@"scripts\deploy.ps1")]
    [InlineData(@"file:///C:/Users/Someone/variables.yaml")]
    public void CommonLocalPathsNeverAppearInDefaultText(string raw)
    {
        Assert.Equal("Factory folder", TechnicalValuePresentation.Summary(raw, "Factory folder"));
        Assert.True(TechnicalValuePresentation.HasDetails(raw));
    }

    [Theory]
    [InlineData("Failed to read \"C:\\My Factory\\variables.yaml\". Retry.", "Failed to read [local path]. Retry.")]
    [InlineData("Failed to read '/c/My Factory/variables.yaml'. Retry.", "Failed to read [local path]. Retry.")]
    [InlineData("Saved to C:\\My Factory\\variables.yaml", "Saved to [local path]")]
    [InlineData("Saved to /c/My Factory/variables.yaml", "Saved to [local path]")]
    public void MixedTextConcealsTheEntirePathIncludingSpaces(string raw, string expected) =>
        Assert.Equal(expected, TechnicalValuePresentation.Summary(raw));

    [Theory]
    [InlineData("https://example.com/service/resources?view=full")]
    [InlineData("http://127.0.0.1:8765")]
    [InlineData("wss://example.com/terminal")]
    [InlineData("git://example.com/org/repo.git")]
    [InlineData("https://vault.vault.azure.net/secrets/certificate-name")]
    [InlineData("mrvel-1-project011-sdc-dev-007")]
    [InlineData("your-account/your-ai-factory")]
    [InlineData("10.42.0.0/24")]
    [InlineData("dev: Available; stage: Not deployed")]
    [InlineData("Generated 2026-09-09T12:15:00Z")]
    [InlineData("")]
    public void OrdinaryNamesCidrAndNetworkUrlsRemainReadable(string raw)
    {
        Assert.Equal(raw, TechnicalValuePresentation.Summary(raw));
        Assert.False(TechnicalValuePresentation.HasDetails(raw));
    }

    [Fact]
    public void AzureUrlsRetainResourceNamesButNeverGuidSegments()
    {
        var raw = $"https://portal.azure.com/#@{Id}/resource/subscriptions/{Id}/resourceGroups/my-rg/overview";
        var display = TechnicalValuePresentation.Summary(raw);
        Assert.Equal("https://portal.azure.com/#@[id]/resource/subscriptions/[id]/resourceGroups/my-rg/overview", display);
    }

    [Fact]
    public void CommandsAlwaysRequireExplicitDisclosureEvenWithoutDetectableIds()
    {
        const string command = "bash deploy.sh --project 123 --project-only";
        Assert.Equal("Exact command", TechnicalValuePresentation.Summary(command, "Exact command", conceal: true));
    }

    [Fact]
    public void DuplicateMaskedChoicesRemainDistinctAndOrdered()
    {
        var raw = new[] { $"Development ({Id})", $"Development ({Guid.NewGuid()})", "Production" };
        var labels = TechnicalValuePresentation.ChoiceLabels(raw);
        Assert.Equal(["Development [id] · option 1", "Development [id] · option 2", "Production"], labels);
        Assert.Equal($"Development ({Id})", raw[0]);
    }

    [Theory]
    [InlineData("api_key", true)]
    [InlineData("client_secret", true)]
    [InlineData("service_principal_password", true)]
    [InlineData("access_token", true)]
    [InlineData("refresh_token", true)]
    [InlineData("service_principal_secret", true)]
    [InlineData("environment_password", true)]
    [InlineData("Credential", true)]
    [InlineData("github_pat", true)]
    [InlineData("CredentialEnv", false)]
    [InlineData("api_key_env", false)]
    [InlineData("certificate_secret_id", false)]
    [InlineData("AppGatewayCertificateSecretId", false)]
    [InlineData("CredentialEnvironmentVariable", false)]
    [InlineData("subscription_id", false)]
    public void SecretFieldsCannotAcquireRawValueTooltips(string context, bool expected) =>
        Assert.Equal(expected, TechnicalValuePresentation.IsSecret(context));

    [Theory]
    [InlineData("_save_folder", true)]
    [InlineData("script_path", true)]
    [InlineData("template_file", true)]
    [InlineData("ConfigurationFile", true)]
    [InlineData("SourceDirectory", true)]
    [InlineData("DestinationPath", true)]
    [InlineData("Profile", false)]
    [InlineData("file_share_name", false)]
    [InlineData("resource_group_name", false)]
    [InlineData("default_subnet_cidr", false)]
    public void SchemaLocalFieldsConcealEvenBareRelativeFileNames(string context, bool expected) =>
        Assert.Equal(expected, TechnicalValuePresentation.IsLocalField(context));

    [Fact]
    public void DisplayNeverWritesTheUnderlyingConfigurationAndExplicitEditStillDoes()
    {
        var writes = new List<JsonNode?>();
        var field = new ConfigFieldViewModel("subscription_id", "Subscription id", "",
            JsonValue.Create(Id), null, [], (_, value) => writes.Add(value));
        Assert.Equal("Subscription id", TechnicalValuePresentation.Summary(field.Value, field.Label));
        Assert.Equal(Id, field.Value);
        Assert.Empty(writes);
        var updated = Guid.NewGuid().ToString();
        field.Value = updated;
        Assert.Equal(updated, Assert.Single(writes)!.GetValue<string>());
        Assert.Equal("Subscription id", TechnicalValuePresentation.Summary(field.Value, field.Label));
    }

    [Fact]
    public void CaptionCannotAccidentallyRevealAnotherTechnicalValue()
    {
        Assert.Equal("Details", TechnicalValuePresentation.Summary(Id, @"C:\My Factory", true));
        Assert.Equal("", TechnicalValuePresentation.Summary(null));
    }
}
