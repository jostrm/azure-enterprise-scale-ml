using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class TicketTabsViewModel : ObservableObject
{
    private bool _isConnectionsTab;
    private Task? _ticketsLoad;
    private Task? _connectionsLoad;

    public TicketTabsViewModel(TicketsViewModel tickets, TicketConnectionsViewModel ticketConnections)
    {
        Tickets = tickets;
        TicketConnections = ticketConnections;
        ShowTicketsCommand = new AsyncCommand(() => ShowTabAsync(false));
        ShowConnectionsCommand = new AsyncCommand(() => ShowTabAsync(true));
        TicketConnections.ConnectionsChanged += (_, _) => Tickets.ApplyConnections(TicketConnections.Connections);
    }

    public TicketsViewModel Tickets { get; }
    public TicketConnectionsViewModel TicketConnections { get; }
    public AsyncCommand ShowTicketsCommand { get; }
    public AsyncCommand ShowConnectionsCommand { get; }
    public bool IsTicketsTab => !_isConnectionsTab;
    public bool IsConnectionsTab => _isConnectionsTab;
    public string TicketsTabDescription => IsTicketsTab ? "Tickets tab, selected" : "Tickets tab";
    public string ConnectionsTabDescription => IsConnectionsTab ? "Ticket Connections tab, selected" : "Ticket Connections tab";

    public void SelectTab(bool connections)
    {
        if (!SetProperty(ref _isConnectionsTab, connections, nameof(IsConnectionsTab))) return;
        OnPropertyChanged(nameof(IsTicketsTab));
        OnPropertyChanged(nameof(TicketsTabDescription));
        OnPropertyChanged(nameof(ConnectionsTabDescription));
    }

    public Task ShowTabAsync(bool connections)
    {
        SelectTab(connections);
        return LoadSelectedTabAsync();
    }

    // Each tab loads once; explicit Reload commands retry errors without losing drafts on tab changes.
    public Task LoadSelectedTabAsync() => IsConnectionsTab
        ? _connectionsLoad ??= TicketConnections.LoadAsync()
        : _ticketsLoad ??= Tickets.LoadAsync();
}
