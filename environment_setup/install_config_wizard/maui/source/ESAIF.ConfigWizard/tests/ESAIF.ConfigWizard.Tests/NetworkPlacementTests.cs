using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class NetworkPlacementTests
{
    [Fact]
    public async Task GuidanceUsesActualLoadedRangesAndUpdatesOnEachRelevantChange()
    {
        var state = State();
        var client = new Client();
        using var vm = Model(state, client);
        await vm.GuidanceTask;
        Assert.Equal("61/62/63 @ 172.16.XX.0/24", vm.CapacityDescription);
        Assert.Contains("Stage/Test: 62", vm.CurrentRanges);
        var octet = 58;
        foreach (var key in new[] { "dev_cidr_range", "test_cidr_range", "prod_cidr_range" })
        {
            state[key] = (octet++).ToString();
            vm.Synchronize(state);
            Assert.False(vm.CanOptimize);
            await vm.GuidanceTask;
        }
        Assert.Equal("58/59/60 @ 172.16.XX.0/24", vm.CapacityDescription);
        state["common_vnet_cidr"] = "172.16.XX.0/25";
        vm.Synchronize(state);
        await vm.GuidanceTask;
        Assert.Equal("58/59/60 @ 172.16.XX.0/25", vm.CapacityDescription);
        Assert.Equal(5, client.Calls);
        state["title"] = "Unrelated";
        vm.Synchronize(state);
        await vm.GuidanceTask;
        Assert.Equal(5, client.Calls);
        Assert.All(client.Requests, request => Assert.False(request.ContainsKey("secret")));
    }

    [Fact]
    public async Task LateResponsesCannotReplaceCurrentGuidanceOrOptimization()
    {
        var state = State();
        var started = new TaskCompletionSource();
        var previous = new TaskCompletionSource<NetworkPlacementPreview>();
        var client = new Client
        {
            Handler = input =>
            {
                if (input["dev_cidr_range"]!.ToString() != "61") return Task.FromResult(Result(input));
                started.SetResult();
                return previous.Task;
            }
        };
        using var vm = Model(state, client);
        await started.Task;
        var first = vm.GuidanceTask;
        state["dev_cidr_range"] = "0";
        vm.Synchronize(state);
        await vm.GuidanceTask;
        previous.SetResult(new() { Guidance = "stale", CanOptimize = false });
        await first;
        Assert.Equal("0/62/63 @ 172.16.XX.0/24", vm.CapacityDescription);
    }

    [Fact]
    public async Task OptimizationOnlyAppliesAfterConfirmationAndChangesOnlyRanges()
    {
        var state = State();
        var before = state.ToJsonString();
        ScalingModeViewModel? vm = null;
        using var model = vm = Model(state, new Client(), (expected, changes) =>
        {
            ScalingModeConfiguration.ApplyOptimization(state, expected, changes);
            vm!.Synchronize(state);
        });
        await model.GuidanceTask;
        var preview = model.PrepareOptimization();
        Assert.Equal(before, state.ToJsonString());
        Assert.Contains("61 -> 0", preview.Message);
        Assert.Contains("No Azure subnets are moved", preview.Message);
        Assert.True(model.ApplyOptimization(preview));
        Assert.False(model.ApplyOptimization(preview));
        await model.GuidanceTask;
        Assert.Equal("0", state["dev_cidr_range"]!.ToString());
        Assert.Equal("1", state["test_cidr_range"]!.ToString());
        Assert.Equal("2", state["prod_cidr_range"]!.ToString());
        Assert.Equal("172.16.XX.0/24", state["common_vnet_cidr"]!.ToString());
        Assert.Equal("keep", state["secret"]!.ToString());
    }

    [Fact]
    public async Task ChangesWhileConfirmationOpenInvalidateItEvenAfterGuidanceRefresh()
    {
        var state = State();
        var applied = false;
        using var vm = Model(state, new Client(), (_, _) => applied = true);
        await vm.GuidanceTask;
        var confirmation = vm.PrepareOptimization();
        state["prod_cidr_range"] = "50";
        vm.Synchronize(state);
        await vm.GuidanceTask;
        Assert.False(vm.ApplyOptimization(confirmation));
        Assert.False(applied);
    }

    [Fact]
    public async Task ApiFailureRemovesStalePresetCapacityAndDisablesOptimization()
    {
        var state = State();
        using var vm = Model(state, new Client { Handler = _ => throw new HttpRequestException("API offline") });
        await vm.GuidanceTask;
        Assert.Contains("Capacity unavailable", vm.CapacityDescription);
        Assert.Contains("API offline", vm.CapacityDescription);
        Assert.False(vm.CanOptimize);
        Assert.False(vm.IsGuidanceLoading);
    }

    [Fact]
    public void OptimizationRejectsUnrelatedWritesAndOutdatedStateAtomically()
    {
        var state = State();
        var expected = NetworkPlacementInput.Capture(state);
        var before = state.ToJsonString();
        Assert.Throws<InvalidDataException>(() => ScalingModeConfiguration.ApplyOptimization(state, expected,
            new() { ["dev_cidr_range"] = "0", ["common_vnet_cidr"] = "10.0.0.0/8" }));
        Assert.Equal(before, state.ToJsonString());
        state["test_cidr_range"] = "50";
        Assert.Throws<InvalidOperationException>(() => ScalingModeConfiguration.ApplyOptimization(state, expected,
            new() { ["dev_cidr_range"] = "0" }));
        Assert.Equal("61", state["dev_cidr_range"]!.ToString());
    }

    [Fact]
    public async Task OverlappingLoadedNetworksNeverEnableOptimizeEvenIfOldApiOffersIt()
    {
        var state = State();
        state["common_vnet_cidr"] = "172.16.0.0/18";
        using var vm = Model(state, new Client
        {
            Handler = _ => Task.FromResult(new NetworkPlacementPreview
            {
                Guidance = "Old API guidance",
                CanOptimize = true,
                OptimizationDescription = "Old unsafe placement",
                OptimizationChanges = new() { ["dev_cidr_range"] = "0" }
            })
        });
        await vm.GuidanceTask;
        Assert.Contains("overlaps", vm.PeeringStatus);
        Assert.Contains("Cannot peer", vm.CapacityDescription);
        Assert.False(vm.CanOptimize);
    }

    [Fact]
    public async Task MalformedOverlappingOptimizationIsRejectedBeforeShowingConfirmation()
    {
        var state = State();
        using var vm = Model(state, new Client
        {
            Handler = _ => Task.FromResult(new NetworkPlacementPreview
            {
                Guidance = "Unsafe response", IsPeerable = true, CanOptimize = true,
                OptimizationDescription = "Collapse all environments",
                OptimizationChanges = new() { ["dev_cidr_range"] = "0", ["test_cidr_range"] = "0", ["prod_cidr_range"] = "0" }
            })
        });
        await vm.GuidanceTask;
        Assert.Contains("overlaps", vm.CapacityDescription);
        Assert.False(vm.CanOptimize);
        Assert.Equal("61", state["dev_cidr_range"]!.ToString());
    }

    [Fact]
    public void OverlappingDefaultProfileCannotBeAppliedEvenFromOldSchema()
    {
        var state = State();
        var before = state.ToJsonString();
        var defaults = NetworkPlacementInput.Capture(state);
        defaults["common_vnet_cidr"] = "172.16.0.0/18";
        var schema = new FactorySchema
        {
            Options = new() { ["scaling_modes"] = new JsonObject
            {
                ["shared-subscriptions"] = new JsonObject { ["network_defaults"] = defaults }
            } }
        };
        using var vm = new ScalingModeViewModel(schema, state, _ => { }, () => { });
        Assert.False(vm.CanApplyDefaults);
        Assert.Throws<InvalidOperationException>(() => ScalingModeConfiguration.ApplyDefaults(state, schema));
        Assert.Equal(before, state.ToJsonString());
    }

    private static ScalingModeViewModel Model(JsonObject state, Client client, Action<JsonObject, JsonObject>? apply = null) =>
        new(new FactorySchema(), state, _ => { }, () => { }, client, apply ?? ((_, _) => { }));

    private static JsonObject State() => new()
    {
        ["scaling-mode"] = "shared-subscriptions", ["common_vnet_cidr"] = "172.16.XX.0/24",
        ["dev_cidr_range"] = "61", ["test_cidr_range"] = "62", ["prod_cidr_range"] = "63",
        ["common_subnet_cidr"] = "172.16.XX.0/26", ["common_subnet_scoring_cidr"] = "172.16.XX.64/26",
        ["common_pbi_subnet_cidr"] = "172.16.XX.128/26", ["common_bastion_subnet_cidr"] = "172.16.XX.192/26",
        ["secret"] = "keep"
    };

    private static NetworkPlacementPreview Result(JsonObject state) => new()
    {
        Guidance = $"{state["dev_cidr_range"]}/{state["test_cidr_range"]}/{state["prod_cidr_range"]} @ {state["common_vnet_cidr"]}",
        IsPeerable = true,
        CanOptimize = true,
        OptimizationDescription = "Place common subnets at the beginning of each separate VNet.",
        OptimizationChanges = new() { ["dev_cidr_range"] = "0", ["test_cidr_range"] = "1", ["prod_cidr_range"] = "2" }
    };

    private sealed class Client : INetworkPlacementClient
    {
        public int Calls { get; private set; }
        public List<JsonObject> Requests { get; } = [];
        public Func<JsonObject, Task<NetworkPlacementPreview>> Handler { get; init; } = input => Task.FromResult(Result(input));
        public Task<NetworkPlacementPreview> PreviewNetworkPlacementAsync(JsonObject state, CancellationToken cancellationToken = default)
        {
            ++Calls;
            Requests.Add((JsonObject)state.DeepClone());
            return Handler(state);
        }
    }
}
