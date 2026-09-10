using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class CatalogSettingsEditorTests
{
    private static readonly CatalogSettingsScope Scope = new(@"C:\catalog", "factory-a", "scale-a", null);
    private static FactoryCatalogSettings Settings() => new()
    {
        ContractVersion = 1, Revision = "revision-1", FactoryId = Scope.FactoryId, ScaleSetId = Scope.ScaleSetId,
        State = new() { ["technical_admins_ad_object_id"] = "old-reference", ["enabled"] = true, ["workers"] = 2 },
        FieldKeys = ["technical_admins_ad_object_id", "enabled", "workers"]
    };
    private static FactorySchema Schema(FactoryCatalogSettings settings) => new() { Defaults = (JsonObject)settings.State.DeepClone() };

    [Fact]
    public void OnlyEditedScalarValuesAreSubmittedAndSourceStateIsIsolated()
    {
        var settings = Settings();
        var before = settings.State.ToJsonString();
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, Schema(settings));
        var reference = editor.Fields.Single(field => field.Key == "technical_admins_ad_object_id");
        reference.Value = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA";
        var delta = editor.BuildDelta(Scope, settings.Revision);
        Assert.Single(delta);
        Assert.Equal(reference.Value, delta[reference.Key]!.GetValue<string>());
        Assert.Equal(before, settings.State.ToJsonString());
        Assert.Contains("old-reference", editor.ReviewDelta(delta));
        Assert.Contains(reference.Value, editor.ReviewDelta(delta));
        reference.Value = "old-reference";
        Assert.False(editor.IsDirty);
        Assert.Throws<InvalidOperationException>(() => editor.BuildDelta(Scope, settings.Revision));
    }

    [Fact]
    public void WhitelistDoesNotExposeSecretsNestedValuesOrImmutableFieldsFromDefaults()
    {
        var settings = Settings() with
        {
            State = new() { ["technical_admins_ad_object_id"] = "allowed", ["api_key"] = "NEVER-SHOW",
                ["projectName"] = "IMMUTABLE", ["outside_whitelist"] = "HIDDEN" },
            FieldKeys = ["technical_admins_ad_object_id", "api_key", "projectName"]
        };
        var schema = new FactorySchema { Defaults = new() { ["default_secret"] = "NEVER-SHOW", ["unlisted"] = "HIDDEN" } };
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, schema);
        Assert.Equal("technical_admins_ad_object_id", Assert.Single(editor.Fields).Key);
        Assert.DoesNotContain("NEVER-SHOW", editor.Status);
        Assert.Throws<InvalidDataException>(() => editor.ReviewDelta(new() { ["api_key"] = "forbidden" }));
        var nested = settings with { State = new() { ["nested"] = new JsonObject() }, FieldKeys = ["nested"] };
        Assert.Throws<InvalidDataException>(() => editor.Load(Scope, nested, schema));
    }

    [Fact]
    public void NetworkModeUpdatesOnlyItsWhitelistedChangedDependentFlags()
    {
        var (settings, schema) = NetworkSettings();
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, schema);
        var network = editor.Fields.Single(field => field.Key == "network_mode").NetworkMode!;
        network.IsPrivate = true;
        var delta = editor.BuildDelta(Scope, settings.Revision);
        Assert.Equal(3, delta.Count);
        Assert.Equal("private", delta["network_mode"]!.GetValue<string>());
        Assert.False(delta["allowPublicAccessWhenBehindVnet"]!.GetValue<bool>());
        Assert.False(delta["enablePublicGenAIAccess"]!.GetValue<bool>());
        Assert.False(delta.ContainsKey("enablePublicAccessWithPerimeter"));
        Assert.Equal("public", settings.State["network_mode"]!.GetValue<string>());
    }

    [Fact]
    public void DependentChangesCannotEscapeServerWhitelist()
    {
        var (settings, schema) = NetworkSettings();
        settings = settings with { FieldKeys = ["network_mode", "allowPublicAccessWhenBehindVnet"] };
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, schema);
        editor.Fields.Single(field => field.Key == "network_mode").NetworkMode!.IsPrivate = true;
        Assert.True(editor.HasErrors);
        Assert.Equal(0, editor.ChangedCount);
        Assert.Contains("whitelist", editor.Status);
        Assert.Throws<InvalidOperationException>(() => editor.BuildDelta(Scope, settings.Revision));
    }

    [Fact]
    public void RevisionChangesRetainDraftButRequireExplicitReload()
    {
        var settings = Settings();
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, Schema(settings));
        editor.Fields.Single(field => field.Key == "workers").Value = "3";
        editor.UpdateContext(Scope, "revision-2");
        Assert.True(editor.IsStale);
        Assert.Equal("3", editor.Fields.Single(field => field.Key == "workers").Value);
        Assert.Throws<InvalidOperationException>(() => editor.BuildDelta(Scope, "revision-2"));
        editor.Load(Scope, settings with { Revision = "revision-2" }, Schema(settings));
        Assert.False(editor.IsDirty);
        Assert.False(editor.IsStale);
    }

    [Fact]
    public void ScopeChangeClearsValuesAndWrongScopeReadIsRejected()
    {
        var settings = Settings();
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, Schema(settings));
        var other = Scope with { FactoryId = "factory-b" };
        editor.UpdateContext(other, settings.Revision);
        Assert.Empty(editor.Fields);
        Assert.False(editor.IsLoaded);
        Assert.Throws<InvalidDataException>(() => editor.Load(other, settings, Schema(settings)));
        Assert.Throws<InvalidOperationException>(() => editor.BuildDelta(Scope, settings.Revision));
    }

    [Fact]
    public void ScalarSchemaErrorsBlockPrepareAndDoNotBecomeStringOverrides()
    {
        var settings = Settings();
        var editor = new CatalogSettingsEditor();
        editor.Load(Scope, settings, Schema(settings));
        var workers = editor.Fields.Single(field => field.Key == "workers");
        workers.Value = "not-an-integer";
        Assert.True(editor.HasErrors);
        Assert.Throws<InvalidOperationException>(() => editor.BuildDelta(Scope, settings.Revision));
        editor.Fields.Single(field => field.Key == "technical_admins_ad_object_id").Value = "changed";
        Assert.Equal("not-an-integer", workers.Value);
        workers.Value = "4";
        Assert.False(editor.HasErrors);
        Assert.Equal(4, editor.BuildDelta(Scope, settings.Revision)["workers"]!.GetValue<int>());
    }

    private static (FactoryCatalogSettings Settings, FactorySchema Schema) NetworkSettings()
    {
        var settings = Settings() with
        {
            State = new() { ["network_mode"] = "public", ["allowPublicAccessWhenBehindVnet"] = true,
                ["enablePublicGenAIAccess"] = true, ["enablePublicAccessWithPerimeter"] = false },
            FieldKeys = ["network_mode", "allowPublicAccessWhenBehindVnet", "enablePublicGenAIAccess", "enablePublicAccessWithPerimeter"]
        };
        var schema = new FactorySchema
        {
            Defaults = (JsonObject)settings.State.DeepClone(),
            Options = new() { ["network_modes"] = new JsonObject
            {
                ["public"] = new JsonObject { ["allowPublicAccessWhenBehindVnet"] = true, ["enablePublicGenAIAccess"] = true, ["enablePublicAccessWithPerimeter"] = false },
                ["private"] = new JsonObject { ["allowPublicAccessWhenBehindVnet"] = false, ["enablePublicGenAIAccess"] = false, ["enablePublicAccessWithPerimeter"] = false }
            } }
        };
        return (settings, schema);
    }
}
