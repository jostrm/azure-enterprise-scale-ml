using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class EnvironmentVNetAddressingTests
{
    [Theory]
    [InlineData("172.16.XX.0/18", "0", "64", "128")]
    [InlineData("172.16.XX.0/20", "0", "16", "32")]
    [InlineData("172.16.XX.0/24", "61", "62", "63")]
    [InlineData("10.80.XX.0/18", "0", "64", "192")]
    public void XxResolvesAlignedDistinctEnvironmentNetworks(string cidr, string dev, string stage, string prod)
    {
        var state = State(cidr, dev, stage, prod);
        var before = state.ToJsonString();
        Assert.Empty(EnvironmentVNetAddressing.ValidationError(state));
        EnvironmentVNetAddressing.RequireNonOverlapping(state);
        Assert.Equal(before, state.ToJsonString());
    }

    [Theory]
    [InlineData("172.16.0.0/18", "15", "20", "25", "overlaps")]
    [InlineData("172.16.0.0/16", "61", "62", "63", "overlaps")]
    [InlineData("172.16.XX.0/18", "0", "0", "128", "overlaps")]
    [InlineData("172.16.XX.0/18", "61", "62", "63", "aligned")]
    [InlineData("172.16.XX.0/20", "0", "20", "32", "aligned")]
    [InlineData("172.16.XX.0/18", "0", "", "128", "third octet")]
    [InlineData("172.16.XX.0/18", "0", "64", "256", "third octet")]
    [InlineData("::/64", "0", "64", "128", "IPv4")]
    public void InvalidOrOverlappingPlanIsRejectedWithoutRewriting(string cidr, string dev, string stage, string prod, string message)
    {
        var state = State(cidr, dev, stage, prod);
        var before = state.ToJsonString();
        Assert.Contains(message, EnvironmentVNetAddressing.ValidationError(state));
        Assert.Throws<InvalidOperationException>(() => EnvironmentVNetAddressing.RequireNonOverlapping(state));
        Assert.Equal(before, state.ToJsonString());
    }

    private static JsonObject State(string cidr, string dev, string stage, string prod) => new()
    {
        ["common_vnet_cidr"] = cidr, ["dev_cidr_range"] = dev,
        ["test_cidr_range"] = stage, ["prod_cidr_range"] = prod
    };
}
