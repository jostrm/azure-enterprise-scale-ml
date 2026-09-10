using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class AzureAuthenticationViewModelTests
{
    [Fact]
    public async Task VerifiedStatus_ChangesLoginButtonToLogout()
    {
        var client = new StubClient { Status = SignedIn };
        var model = new AzureAuthenticationViewModel(client);
        Assert.Equal("Login to Azure", model.ButtonText);
        await model.RefreshAsync(@"C:\factory");
        Assert.Equal("Logout", model.ButtonText);
        Assert.Equal("user@example.test", model.AccountName);
        Assert.Equal(0, client.LoginCalls);
        Assert.Equal(0, client.LogoutCalls);
        Assert.Equal(@"C:\factory", client.Folder);
    }

    [Fact]
    public async Task ExpiredTenant_KeepsLoginButtonAndSelectsTheTenantNeedingAuthentication()
    {
        var client = new StubClient
        {
            Status = new AzureAuthenticationStatus
            {
                State = "login_required",
                Tenants =
                [
                    new() { TenantId = "valid", NeedsLogin = false },
                    new() { TenantId = "expired", NeedsLogin = true }
                ],
                Message = "One tenant needs interactive sign-in."
            }
        };
        var model = new AzureAuthenticationViewModel(client);
        await model.RefreshAsync(@"C:\factory");
        Assert.Equal("Login to Azure", model.ButtonText);
        Assert.Single(model.LoginTenants);
        Assert.Equal("expired", model.SuggestedTenantId);
        Assert.True(model.CanAuthenticate);
    }

    [Fact]
    public async Task OnlyExplicitActions_InvokeLoginAndLogout()
    {
        var client = new StubClient();
        var model = new AzureAuthenticationViewModel(client);
        await model.RefreshAsync(null);
        Assert.Equal(0, client.LoginCalls);
        await model.LoginAsync(null, "tenant");
        Assert.Equal(1, client.LoginCalls);
        Assert.Equal("tenant", client.Tenant);
        Assert.Equal("Logout", model.ButtonText);
        await model.LogoutAsync(null);
        Assert.Equal(1, client.LogoutCalls);
        Assert.Equal("Login to Azure", model.ButtonText);
        Assert.False(model.IsLoggedIn);
    }

    [Fact]
    public async Task ClosingMenu_CancelsPollingAndReopeningResumesWithoutAnotherLogin()
    {
        using var lifetime = new CancellationTokenSource();
        var client = new StubClient
        {
            Status = SignedIn,
            LoginStatus = new AzureAuthenticationStatus
            {
                State = "signing_in", OperationId = "job", Message = "Complete Microsoft sign-in."
            }
        };
        var model = new AzureAuthenticationViewModel(client);
        var login = model.LoginAsync(@"C:\factory", "tenant", lifetime.Token);
        Assert.True(model.IsWorking);
        Assert.False(model.CanAuthenticate);
        lifetime.Cancel();
        await login;
        Assert.Contains("Complete Microsoft sign-in", model.Message);
        await model.RefreshAsync(@"C:\factory");
        Assert.Equal(1, client.LoginCalls);
        Assert.Equal(1, client.OperationCalls);
        Assert.Equal("Logout", model.ButtonText);
        Assert.False(model.IsWorking);
    }

    [Fact]
    public async Task FailedStatusCheck_DoesNotShowAStaleVerifiedSession()
    {
        var client = new StubClient { Status = SignedIn };
        var model = new AzureAuthenticationViewModel(client);
        await model.RefreshAsync(null);
        client.Failure = new HttpRequestException("Python API unavailable.");
        await model.RefreshAsync(null);
        Assert.False(model.IsLoggedIn);
        Assert.Equal("Login to Azure", model.ButtonText);
        Assert.Contains("Python API unavailable", model.Message);
    }

    [Fact]
    public async Task ChangedFactoryContext_RechecksStatusAfterPendingOperationCompletes()
    {
        using var lifetime = new CancellationTokenSource();
        var client = new StubClient
        {
            LoginStatus = new AzureAuthenticationStatus { State = "signing_in", OperationId = "job" },
            Status = new AzureAuthenticationStatus { State = "login_required", Message = "New tenant needs sign-in." }
        };
        var model = new AzureAuthenticationViewModel(client);
        var login = model.LoginAsync(@"C:\first", "tenant", lifetime.Token);
        lifetime.Cancel();
        await login;
        await model.RefreshAsync(@"C:\second");
        Assert.Equal(@"C:\second", client.Folder);
        Assert.Equal("Login to Azure", model.ButtonText);
        Assert.Contains("New tenant", model.Message);
    }

    private static AzureAuthenticationStatus SignedIn => new()
    {
        State = "signed_in", IsLoggedIn = true, AccountName = "user@example.test",
        Message = "Sign-in verified."
    };

    [Fact]
    public async Task SuccessfulLogin_RefreshesOnceButOpeningMenuDoesNot()
    {
        var client = new StubClient { Status = SignedIn };
        var refresher = new StubRefresher();
        var model = new AzureAuthenticationViewModel(client, refresher);
        await model.RefreshAsync(null);
        Assert.Equal(0, refresher.Calls);
        await model.LoginAsync("factory", "tenant");
        Assert.Equal(1, refresher.Calls);
        Assert.Contains("Configuration refreshed", model.Message);
        await model.RefreshAsync("factory");
        Assert.Equal(1, refresher.Calls);
        await model.LogoutAsync("factory");
        Assert.Equal(1, refresher.Calls);
    }

    [Fact]
    public async Task PostLoginRefreshFailure_DoesNotPretendAuthenticationFailed()
    {
        var model = new AzureAuthenticationViewModel(new StubClient(),
            new StubRefresher { Failure = new HttpRequestException("Data unavailable") });
        await model.LoginAsync("factory", "tenant");
        Assert.True(model.IsLoggedIn);
        Assert.Equal("Logout", model.ButtonText);
        Assert.Contains("sign-in succeeded", model.Message);
        Assert.Contains("Data unavailable", model.Message);
    }

    [Fact]
    public async Task LoginCompletionRecoveredAfterClosingMenu_AutomaticallyRefreshesOnce()
    {
        using var lifetime = new CancellationTokenSource();
        var client = new StubClient
        {
            Status = SignedIn,
            LoginStatus = new AzureAuthenticationStatus { State = "signing_in", OperationId = "job" }
        };
        var refresher = new StubRefresher();
        var model = new AzureAuthenticationViewModel(client, refresher);
        var login = model.LoginAsync("factory", "tenant", lifetime.Token);
        lifetime.Cancel();
        await login;
        Assert.Equal(0, refresher.Calls);
        await model.RefreshAsync("factory");
        Assert.Equal(1, refresher.Calls);
        await model.RefreshAsync("factory");
        Assert.Equal(1, refresher.Calls);
    }

    private sealed class StubRefresher : IPostAzureLoginRefresh
    {
        public int Calls { get; private set; }
        public Exception? Failure { get; init; }
        public Task<string> RefreshAsync()
        {
            Calls++;
            return Failure is null ? Task.FromResult("Configuration refreshed.")
                : Task.FromException<string>(Failure);
        }
    }

    private sealed class StubClient : IAzureAuthenticationClient
    {
        public AzureAuthenticationStatus Status { get; set; } = new() { State = "signed_out" };
        public AzureAuthenticationStatus LoginStatus { get; init; } = SignedIn;
        public Exception? Failure { get; set; }
        public int LoginCalls { get; private set; }
        public int LogoutCalls { get; private set; }
        public int OperationCalls { get; private set; }
        public string? Folder { get; private set; }
        public string? Tenant { get; private set; }

        public Task<AzureAuthenticationStatus> GetAzureAuthenticationStatusAsync(
            string? aiFactoryFolder, CancellationToken cancellationToken = default)
        {
            Folder = aiFactoryFolder;
            return Failure is null ? Task.FromResult(Status) : Task.FromException<AzureAuthenticationStatus>(Failure);
        }
        public Task<AzureAuthenticationStatus> LoginToAzureAsync(
            string? aiFactoryFolder, string? tenantId, CancellationToken cancellationToken = default)
        {
            LoginCalls++;
            Folder = aiFactoryFolder;
            Tenant = tenantId;
            return Task.FromResult(LoginStatus);
        }
        public Task<AzureAuthenticationStatus> LogoutFromAzureAsync(
            string? aiFactoryFolder, CancellationToken cancellationToken = default)
        {
            LogoutCalls++;
            return Task.FromResult(new AzureAuthenticationStatus { State = "signed_out" });
        }
        public Task<AzureAuthenticationStatus> GetAzureAuthenticationOperationAsync(
            string operationId, CancellationToken cancellationToken = default)
        {
            OperationCalls++;
            return Task.FromResult(SignedIn with { OperationId = operationId });
        }
    }
}
