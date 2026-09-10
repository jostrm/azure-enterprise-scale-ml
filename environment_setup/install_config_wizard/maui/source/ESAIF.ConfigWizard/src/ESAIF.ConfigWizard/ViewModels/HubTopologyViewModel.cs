using System.ComponentModel;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class HubTopologyViewModel : ObservableObject
{
    public const string StateKey = "_hub_topology";
    public const string DnsKey = "centralDnsZoneByPolicyInHub";
    public const string OwnHubKey = "enableAIFactoryHub";
    private readonly NetworkModeViewModel? _network;
    private readonly Action<string> _select;
    private string _choice = string.Empty;
    private bool _selecting;
    private bool _notifying;

    public HubTopologyViewModel(JsonObject state, NetworkModeViewModel? network, Action<string> select)
    {
        _network = network;
        _select = select;
        if (network is not null)
        {
            network.PropertyChanged += OnNetworkChanged;
        }
        Synchronize(state);
    }

    public bool CanSelectStandalone => _network is { HasUnrecognizedFlags: false, IsPrivate: false };
    public bool IsStandalone { get => _choice == "standalone"; set { if (value) Select("standalone"); } }
    public bool IsOwnHub { get => _choice == "own-hub"; set { if (value) Select("own-hub"); } }
    public bool IsExternalHub { get => _choice == "external-hub"; set { if (value) Select("external-hub"); } }
    public string DnsPolicy { get; private set; } = "(not set)";
    public string OwnHubEnabled { get; private set; } = "false";
    public bool NeedsChoice => _choice.Length == 0 || IsStandalone && !CanSelectStandalone;
    public string Guidance => IsOwnHub
        ? "For private access with your own hub, use Azure VPN Gateway, Azure Bastion, or Azure Virtual Desktop (AVD). Azure VPN Gateway and a Bastion host are the recommended options to enable in the AI Factory hub. This choice records the topology; it does not deploy a hub or enable these services."
        : IsExternalHub
            ? "Private DNS zones are managed by policy in the external hub. Configure the existing hub connection and DNS settings under Platform networking."
            : NeedsChoice
                ? IsStandalone
                    ? "Standalone is selected by the saved flags. Private or unrecognized networking requires review: choose an own hub or an external hub before saving. No flags have been changed."
                    : "The saved hub flags are invalid. Choose a topology before saving."
                : "Standalone AI Factory: both hub flags are false. This is configuration intent, not a check for deployed infrastructure.";

    public void Synchronize(JsonObject state)
    {
        var dns = state.ContainsKey(DnsKey) ? state[DnsKey]?.ToString() : "false";
        var own = OwnHubValue(state);
        DnsPolicy = bool.TryParse(dns, out var external) ? external.ToString().ToLowerInvariant() : dns ?? "(not set)";
        OwnHubEnabled = bool.TryParse(own, out var enabled) ? enabled.ToString().ToLowerInvariant() : own ?? "(not set)";
        _choice = ChoiceFromState(state);
        Notify();
    }

    public static string ChoiceFromState(JsonObject state)
    {
        var dns = state.ContainsKey(DnsKey) ? state[DnsKey]?.ToString() : "false";
        if (!bool.TryParse(dns, out var external) || !bool.TryParse(OwnHubValue(state), out var own))
            return string.Empty;
        return external ? "external-hub" : own ? "own-hub" : "standalone";
    }

    private static string? OwnHubValue(JsonObject state) => state.ContainsKey(OwnHubKey)
        ? state[OwnHubKey]?.ToString()
        : state[StateKey]?.ToString() == "own-hub" ? "true" : "false";

    private void Select(string choice)
    {
        if (_selecting || _notifying || _choice == choice)
        {
            return;
        }
        if (choice == "standalone" && !CanSelectStandalone)
        {
            return;
        }
        _selecting = true;
        try
        {
            _select(choice);
            _choice = choice;
            DnsPolicy = (choice == "external-hub").ToString().ToLowerInvariant();
            OwnHubEnabled = (choice == "own-hub").ToString().ToLowerInvariant();
            Notify();
        }
        finally
        {
            _selecting = false;
        }
    }

    private void OnNetworkChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(NetworkModeViewModel.IsPrivate))
        {
            Notify();
        }
    }

    private void Notify()
    {
        if (_notifying)
        {
            return;
        }
        _notifying = true;
        try
        {
            foreach (var property in new[] { nameof(CanSelectStandalone), nameof(IsStandalone), nameof(IsOwnHub),
                nameof(IsExternalHub), nameof(DnsPolicy), nameof(OwnHubEnabled), nameof(NeedsChoice), nameof(Guidance) })
            {
                OnPropertyChanged(property);
            }
        }
        finally
        {
            _notifying = false;
        }
    }
}
