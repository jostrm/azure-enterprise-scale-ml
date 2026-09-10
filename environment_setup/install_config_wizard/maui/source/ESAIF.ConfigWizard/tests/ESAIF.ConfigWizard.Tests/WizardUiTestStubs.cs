global using Microsoft.Maui.ApplicationModel;

namespace Microsoft.Maui.ApplicationModel
{
    public static class MainThread
    {
        public static void BeginInvokeOnMainThread(Action action) => action();
        public static Task InvokeOnMainThreadAsync(Action action)
        {
            action();
            return Task.CompletedTask;
        }
    }
}

namespace Microsoft.Maui.Controls
{
    public sealed class Command(Action execute) : System.Windows.Input.ICommand
    {
        public event EventHandler? CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object? parameter) => true;
        public void Execute(object? parameter) => execute();
    }
}
