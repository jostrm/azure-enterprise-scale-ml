namespace ESAIF.ConfigWizard.Controls;

public sealed class DeploymentTerminalView : View
{
    public event EventHandler? TerminalReady;
    public event EventHandler<string>? TerminalInput;
    public event EventHandler<(int Columns, int Rows)>? TerminalResize;
    public event EventHandler? TerminalUnavailable;
    internal Func<string, bool, Task>? OutputWriter { get; set; }
    internal Func<bool, Task>? InputEnabler { get; set; }
    internal Func<Task>? SelectionCopier { get; set; }
    internal Func<Task>? Refitter { get; set; }
    internal Func<Task>? Reloader { get; set; }
    internal string InputScope { get; set; } = string.Empty;

    public Task WriteAsync(string output, bool reset) =>
        OutputWriter?.Invoke(output, reset) ?? Task.FromException(new Services.TerminalUnavailableException("Terminal is not ready."));
    public Task EnableInputAsync(bool enabled) => InputEnabler?.Invoke(enabled) ?? Task.CompletedTask;
    public Task CopySelectionAsync() => SelectionCopier?.Invoke() ?? Task.CompletedTask;
    public Task FitAsync() => Refitter?.Invoke() ?? Task.CompletedTask;
    public Task ReloadAsync() => Reloader?.Invoke() ?? Task.CompletedTask;
    internal void Ready() => TerminalReady?.Invoke(this, EventArgs.Empty);
    internal void Input(string value) => TerminalInput?.Invoke(this, value);
    internal void Resize(int columns, int rows) => TerminalResize?.Invoke(this, (columns, rows));
    internal void Unavailable() => TerminalUnavailable?.Invoke(this, EventArgs.Empty);
}
