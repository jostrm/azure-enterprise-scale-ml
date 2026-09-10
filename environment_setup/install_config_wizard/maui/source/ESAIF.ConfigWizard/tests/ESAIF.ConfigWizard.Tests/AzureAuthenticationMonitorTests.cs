using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class AzureAuthenticationMonitorTests
{
    [Fact]
    public async Task StartupChecksAllScopesAndFirstAuthenticatedTransitionRefreshesOnlyOnce()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        var monitor = new AzureAuthenticationMonitor(fixture.Api, wizard, fixture.Network);
        var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network, monitor);
        Assert.False(coordinator.CanRefresh);
        await monitor.CheckAsync();
        Assert.False(coordinator.CanRefresh);
        Assert.Equal(0, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
        fixture.SignedIn = true;
        await monitor.CheckAsync();
        await coordinator.RefreshAsync(manual: false);
        Assert.True(coordinator.CanRefresh);
        Assert.Equal(2, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
        for (var poll = 0; poll < 3; poll++) { await monitor.CheckAsync(); }
        Assert.Equal(2, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
        fixture.SignedIn = false;
        await monitor.CheckAsync();
        Assert.False(coordinator.CanRefresh);
        fixture.SignedIn = true;
        await monitor.CheckAsync();
        Assert.True(coordinator.CanRefresh);
        Assert.Equal(2, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
    }

    [Fact]
    public async Task AnExpiredSecondaryFactoryDisablesRefreshAndIdentifiesItsLoginTenant()
    {
        var fixture = new FactoryNetworkFixture { SignedIn = true, ExpiredFolder = FactoryNetworkFixture.Gha };
        var wizard = new WizardSession(fixture.Api);
        var monitor = new AzureAuthenticationMonitor(fixture.Api, wizard, fixture.Network);
        var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network, monitor);
        var auth = new AzureAuthenticationViewModel(fixture.Api, monitor: monitor);
        await monitor.CheckAsync();
        Assert.False(coordinator.CanRefresh);
        Assert.Equal(FactoryNetworkFixture.Gha, monitor.LoginFolder);
        Assert.Equal(FactoryNetworkFixture.Gha, monitor.GetLoginFolder(auth.SuggestedTenantId));
        Assert.Equal(FactoryNetworkFixture.GhaSub, Assert.Single(auth.LoginTenants).TenantId);
        Assert.Equal("Login to Azure", auth.ButtonText);
    }

    [Fact]
    public async Task ExpiryFoundByManualPreflightRequestsLoginWithoutStartingCollection()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        var monitor = new AzureAuthenticationMonitor(fixture.Api, wizard, fixture.Network);
        var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network, monitor);
        var prompts = 0;
        coordinator.LoginRequired += (_, _) => prompts++;
        await coordinator.RefreshAsync();
        Assert.Equal(1, prompts);
        Assert.False(coordinator.CanRefresh);
        Assert.Equal(0, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
        Assert.Contains("expired", coordinator.Details);
    }

    [Fact]
    public async Task ConcurrentStatusChecksAreSingleFlightAndUnavailableFailsClosed()
    {
        var fixture = new FactoryNetworkFixture { SignedIn = true,
            AuthenticationGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
        var monitor = new AzureAuthenticationMonitor(fixture.Api, new(fixture.Api), fixture.Network);
        var first = monitor.CheckAsync();
        var second = monitor.CheckAsync();
        Assert.Same(first, second);
        await fixture.AuthenticationStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        fixture.AuthenticationGate.SetResult();
        await Task.WhenAll(first, second);
        Assert.True(monitor.IsLoggedIn);
        Assert.Equal(2, fixture.Count<AzureAuthenticationStatus>());
        fixture.FailAuth = true;
        await monitor.CheckAsync();
        Assert.False(monitor.IsLoggedIn);
        Assert.Contains("unavailable", monitor.Status.Message);
    }

    [Fact]
    public async Task InvalidationDuringCheckCannotRestoreAStaleVerifiedSession()
    {
        var fixture = new FactoryNetworkFixture { SignedIn = true,
            AuthenticationGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
        var monitor = new AzureAuthenticationMonitor(fixture.Api, new(fixture.Api), fixture.Network);
        var check = monitor.CheckAsync();
        await fixture.AuthenticationStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        monitor.Invalidate("Signing out");
        fixture.AuthenticationGate.SetResult();
        await check;
        Assert.False(monitor.IsLoggedIn);
        Assert.Equal("Signing out", monitor.Status.Message);
    }

    [Fact]
    public async Task ForegroundCancellationStopsPollingWithoutLoginOrLogout()
    {
        var fixture = new FactoryNetworkFixture { AuthenticationGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
        var monitor = new AzureAuthenticationMonitor(fixture.Api, new(fixture.Api), fixture.Network);
        using var lifetime = new CancellationTokenSource();
        var check = monitor.CheckAsync(lifetime.Token);
        await fixture.AuthenticationStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        lifetime.Cancel();
        await check;
        Assert.False(monitor.IsLoggedIn);
        fixture.AuthenticationGate = null;
        fixture.SignedIn = true;
        await monitor.CheckAsync();
        Assert.True(monitor.IsLoggedIn);
    }

    [Fact]
    public async Task PostLoginReusesFirstTransitionRefreshButRefreshesANewAuthentication()
    {
        var fixture = new FactoryNetworkFixture { SignedIn = true };
        var wizard = new WizardSession(fixture.Api);
        var monitor = new AzureAuthenticationMonitor(fixture.Api, wizard, fixture.Network);
        var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network, monitor);
        await monitor.CheckAsync();
        await coordinator.RefreshAsync(manual: false);
        var postLogin = new PostAzureLoginRefresh(wizard, coordinator, monitor);
        await postLogin.RefreshAsync();
        Assert.Equal(2, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
        monitor.Invalidate("Login in progress");
        await postLogin.RefreshAsync();
        Assert.Equal(4, fixture.Count<ESAIF.DomainLayer.Operations.OperationsOverview>());
    }

    [Fact]
    public async Task ManualRefreshDetectsExpiryDuringCollectionAndOffersLoginAfterChecks()
    {
        var fixture = new FactoryNetworkFixture { SignedIn = true,
            VerificationGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
        var wizard = new WizardSession(fixture.Api);
        var monitor = new AzureAuthenticationMonitor(fixture.Api, wizard, fixture.Network);
        var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network, monitor);
        var prompts = 0;
        coordinator.LoginRequired += (_, _) => prompts++;
        var refresh = coordinator.RefreshAsync();
        await fixture.VerificationStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        fixture.SignedIn = false;
        fixture.VerificationGate.SetResult();
        await refresh;
        Assert.Equal(1, prompts);
        Assert.Equal(AzureRefreshState.Partial, coordinator.State);
        Assert.False(coordinator.CanRefresh);
    }
}
