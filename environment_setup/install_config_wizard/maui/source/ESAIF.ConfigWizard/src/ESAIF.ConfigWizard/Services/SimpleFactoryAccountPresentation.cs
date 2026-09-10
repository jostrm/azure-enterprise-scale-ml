using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public static class SimpleFactoryAccountPresentation
{
    public static string Label(SimpleFactoryAzureAccount account) =>
        $"Sub-ID: {Prefix(account.SubscriptionId)} | {Prefix(account.SubscriptionName)} | Tenant: {Prefix(account.TenantId)}";

    public static string Details(SimpleFactoryAzureAccount account) =>
        $"Subscription name: {account.SubscriptionName}\nSubscription id: {account.SubscriptionId}\nTenant id: {account.TenantId}";

    private static string Prefix(string value) =>
        string.IsNullOrWhiteSpace(value) ? "Not set" : value.Length <= 5 ? value : value[..5] + "…";
}
