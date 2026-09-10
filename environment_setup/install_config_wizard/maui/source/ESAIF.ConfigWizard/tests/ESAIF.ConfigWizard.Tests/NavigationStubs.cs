global using Microsoft.Maui.Controls;

namespace Microsoft.Maui.Controls
{
    public class Page
    {
        public Func<string[], Task<string>> ChooseAction { get; set; } = _ => Task.FromResult("Cancel");
        public Func<Task<bool>> Confirm { get; set; } = () => Task.FromResult(false);
        public List<string> Alerts { get; } = [];
        public Task<string> DisplayActionSheetAsync(string title, string cancel, string? destruction, params string[] buttons) =>
            ChooseAction(buttons);
        public Task<bool> DisplayAlertAsync(string title, string message, string accept, string cancel) => Confirm();
        public Task DisplayAlertAsync(string title, string message, string cancel)
        {
            Alerts.Add(message);
            return Task.CompletedTask;
        }
    }

    public sealed class Command<T>(Action<T?> execute, Func<T?, bool>? canExecute = null) : System.Windows.Input.ICommand
    {
        public event EventHandler? CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object? parameter) => canExecute?.Invoke(parameter is T value ? value : default) ?? true;
        public void Execute(object? parameter) => execute(parameter is T value ? value : default);
        public void ChangeCanExecute() { }
    }
}

namespace ESAIF.ConfigWizard
{
    public static class AppShell
    {
        public const string WizardPageKey = "wizard";
        public const string TicketsPageKey = "tickets";
        public const string TicketConnectionsPageKey = "ticket-connections";
        public static Task NavigateToWorkspaceAsync(string key) => Task.CompletedTask;
        public static Task PushOperationConfigAsync(string project, string environment, string kind) => Task.CompletedTask;
    }

    namespace Pages
    {
        public static class TechnicalChoicePage
        {
            public static async Task<int> ChooseAsync(Page owner, string title, IReadOnlyList<string> values)
            {
                var labels = Services.TechnicalValuePresentation.ChoiceLabels(values);
                var selected = await owner.DisplayActionSheetAsync(title, "Cancel", null, labels);
                return Array.IndexOf(labels, selected);
            }
        }

        public static class MessageDetailsPage
        {
            public static Task ShowAsync(Page owner, string title, string message, string closeText = "Close") =>
                owner.DisplayAlertAsync(title, message, closeText);
        }
    }
}
