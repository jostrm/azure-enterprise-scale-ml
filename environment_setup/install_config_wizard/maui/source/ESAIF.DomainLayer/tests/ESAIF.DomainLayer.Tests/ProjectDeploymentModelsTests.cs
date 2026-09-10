using System.Text.Json;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.DomainLayer.Tests;

public sealed class ProjectDeploymentModelsTests
{
    [Fact]
    public void DraftPreservesUpdatePatchAndReconciledFailureHistory()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);
        var draft = JsonSerializer.Deserialize<ProjectDeploymentDraft>("""
        {"id":"failed-update","operation":"update","patch":true,"source_environment":"prod",
         "target_environment":"prod","status":"failed","job_id":"job","reconciled_at":"2026-09-09T14:00:00Z"}
        """, options)!;
        Assert.Equal("update", draft.Operation);
        Assert.True(draft.Patch);
        Assert.Equal("failed", draft.Status);
        Assert.Equal("2026-09-09T14:00:00Z", draft.ReconciledAt);
        var legacy = JsonSerializer.Deserialize<ProjectDeploymentDraft>("{}", options)!;
        Assert.Equal("deploy", legacy.Operation);
        Assert.False(legacy.Patch);
        Assert.Null(legacy.ReconciledAt);
    }

    [Fact]
    public void ResourceGroupVerificationPreservesActualHttpResultAndTimestamp()
    {
        var result = JsonSerializer.Deserialize<ScaleSetResourceGroupVerification>("""
        {"scale_set_id":"007","checked_at":"2026-09-08T10:00:00Z","message":"Verified",
        "checks":[{"resource_id":"/subscriptions/sub/resourceGroups/common","http_status":200,"verified":true,"message":"OK"}]}
        """, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        Assert.Equal("007", result.ScaleSetId);
        Assert.Equal("2026-09-08T10:00:00Z", result.CheckedAt);
        var check = Assert.Single(result.Checks);
        Assert.Equal(200, check.HttpStatus);
        Assert.True(check.Verified);
    }

    [Fact]
    public void ScaleSetScopeAndCommonGroupIdentityAreDeserialized()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);
        var saved = JsonSerializer.Deserialize<ScaleSetSummary>("""
        {"scale_set_id":"007","deployment_scope":{"prefix_rg":"mrvel-1-","suffix_rg":"-007",
        "region":"swedencentral","subscription_ids":["sub"]}}
        """, options)!;
        Assert.Equal("007", saved.ScaleSetId);
        Assert.Equal("swedencentral", saved.DeploymentScope!.Region);
        var group = JsonSerializer.Deserialize<AzureResourceGroup>("""
        {"id":"/subscriptions/sub/resourceGroups/common","name":"common","subscriptionId":"sub","tenant_id":"tenant"}
        """, options)!;
        Assert.Equal("sub", group.SubscriptionId);
        Assert.Equal("tenant", group.TenantId);
        Assert.EndsWith("/resourceGroups/common", group.Id);
    }

    [Fact]
    public void InventoryReferencesAndCompleteness_AreExplicitlyDeserialized()
    {
        var value = JsonSerializer.Deserialize<OperationsOverview>("""
        {
          "resource_inventory":{"source":"azure","is_complete":true},
          "projects":[{"project_number":"017","environments":[{
            "environment":"dev","resource_group_refs":[{
              "id":"/subscriptions/sub/resourceGroups/actual","name":"actual",
              "subscription_id":"sub","tenant_id":"tenant"}]
          }]}]
        }
        """, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        Assert.True(value.ResourceInventory.IsComplete);
        var group = Assert.Single(Assert.Single(Assert.Single(value.Projects).Environments).ResourceGroupReferences);
        Assert.Equal("sub", group.SubscriptionId);
        Assert.Equal("tenant", group.TenantId);
        Assert.Equal("/subscriptions/sub/resourceGroups/actual", group.Id);
        Assert.False(new ResourceInventorySummary().IsComplete);
    }

    [Fact]
    public void ProjectScopeAndDeleteResponse_UsePythonContractNames()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);
        var project = JsonSerializer.Deserialize<ProjectSummary>("""
        {"project_number":"017","deployment_scope":{"prefix_rg":"mrvel-1-","suffix_rg":"-007",
        "region":"swedencentral","subscription_ids":["sub"]}}
        """, options)!;
        Assert.Equal("mrvel-1-", project.DeploymentScope!.PrefixResourceGroup);
        Assert.Equal("-007", project.DeploymentScope.SuffixResourceGroup);
        Assert.Equal("sub", Assert.Single(project.DeploymentScope.SubscriptionIds));
        var deleted = JsonSerializer.Deserialize<ProjectConfigurationDeleteResult>(
            """{"deleted_path":"snapshot.json","message":"Deleted"}""", options)!;
        Assert.Equal("snapshot.json", deleted.DeletedPath);
    }
}
