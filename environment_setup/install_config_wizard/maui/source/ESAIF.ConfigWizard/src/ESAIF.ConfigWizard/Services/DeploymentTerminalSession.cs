using System.Net;
using System.Text;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed class DeploymentTerminalSession(
    IProjectTerminalClient client,
    IAiFactoryConnectionProvider connections) : IDeploymentTerminalSession, IFactoryCatalogTerminalSession
{
    private const int BufferLimit = 524_288;
    private readonly StringBuilder _buffer = new();
    private readonly TerminalOutputFilter _filter = new();
    private readonly SemaphoreSlim _inputGate = new(1, 1);
    private AiFactoryConnection? _connection;
    private CancellationTokenSource? _reading;
    private object? _owner;
    private long _cursor;
    private int _generation;
    private int _pendingInput;
    private int _inputEpoch;
    private bool _resizing;
    private (int Columns, int Rows)? _pendingResize;
    private bool _blocked;
    private bool _historyTruncated;
    private FactoryCatalogJob? _catalogJob;
    private string? CurrentJobId => _catalogJob?.Id ?? Draft?.JobId;

    public event EventHandler? Changed;
    public string Folder { get; private set; } = string.Empty;
    public ProjectDeploymentDraft? Draft { get; private set; }
    public string Status { get; private set; } = string.Empty;
    public string Notice { get; private set; } = string.Empty;
    public bool Expanded { get; private set; }
    public bool HasJob => CurrentJobId is { Length: > 0 };
    public string InputScope => $"{_generation}:{_inputEpoch}";
    public bool IsRunning => Status is "queued" or "running";
    public bool CanType => HasJob && Status == "running" && !_blocked && _reading is { IsCancellationRequested: false };
    public string Title => _catalogJob is { } catalog
        ? $"Catalog: {Folder}  |  {catalog.Action}  |  Factory {catalog.FactoryId}  |  Scale set {catalog.ScaleSetId ?? "all"}  |  Job {catalog.Id}"
        : Draft is null ? "Terminal" :
        $"Factory: {Folder}  |  Project {Draft.ProjectNumber}  |  {Draft.SourceEnvironment} → {Draft.TargetEnvironment}  |  Job {Draft.JobId}";

    public Task OpenAsync(string folder, ProjectDeploymentDraft draft)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentNullException.ThrowIfNull(draft);
        ArgumentException.ThrowIfNullOrWhiteSpace(draft.JobId);
        return OpenCoreAsync(folder, draft.JobId, draft.Status, draft, null);
    }

    public Task OpenCatalogAsync(string folder, FactoryCatalogJob job)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentNullException.ThrowIfNull(job);
        ArgumentException.ThrowIfNullOrWhiteSpace(job.Id);
        if (!job.TerminalAvailable || client is not FactoryTerminalRouter)
            throw new NotSupportedException("This catalog job does not provide an interactive terminal.");
        return OpenCoreAsync(folder, job.Id, job.Status, null, job);
    }

    private async Task OpenCoreAsync(string folder, string jobId, string status,
        ProjectDeploymentDraft? draft, FactoryCatalogJob? catalogJob)
    {
        var connection = await connections.GetConnectionAsync();
        await MainThread.InvokeOnMainThreadAsync(() =>
        {
            var sameKind = (_catalogJob is null) == (catalogJob is null);
            if (Folder == folder && CurrentJobId == jobId && sameKind && _connection != connection)
            {
                Block("The API connection changed. Restore the original connection before reconnecting this job.");
                return;
            }
            if (Folder != folder || CurrentJobId != jobId || !sameKind)
            {
                StopReading();
                _generation++;
                _inputEpoch++;
                _connection = connection;
                Folder = folder;
                Draft = draft;
                _catalogJob = catalogJob;
                Status = status;
                _cursor = 0;
                _buffer.Clear();
                _filter.Reset();
                _historyTruncated = false;
                _blocked = false;
                Notice = "Connecting to the owned deployment terminal. Closing this panel does not stop the job.";
            }
            (client as FactoryTerminalRouter)?.Register(connection, folder, jobId,
                catalogJob is null ? FactoryTerminalJobKind.ProjectDeployment : FactoryTerminalJobKind.FactoryCatalog);
            Expanded = true;
            Notify();
        });
    }

    public void ToggleExpanded()
    {
        Expanded = !Expanded;
        if (!Expanded) StopReading();
        Notify();
    }

    public async Task AttachAsync(object owner, Func<string, bool, Task> render)
    {
        if (!HasJob || !Expanded || _owner == owner && _reading is { IsCancellationRequested: false }) return;
        StopReading();
        _owner = owner;
        var source = new CancellationTokenSource();
        _reading = source;
        var generation = _generation;
        try
        {
            await render(_buffer.ToString(), true);
            if (_blocked || !IsCurrent(source, generation)) return;
            await PollAsync(source, generation, render);
        }
        catch (OperationCanceledException) when (source.IsCancellationRequested) { }
        catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
        {
            if (IsCurrent(source, generation))
                Block("Terminal display unavailable. Select Reconnect to reload the retained terminal output.");
        }
    }

    public void Detach(object owner)
    {
        if (_owner != owner) return;
        StopReading();
        _owner = null;
        _inputEpoch++;
        Notify();
    }

    public void Reconnect()
    {
        StopReading();
        _inputEpoch++;
        _blocked = false;
        Expanded = true;
        Notice = "Reconnecting from the last output cursor. Unacknowledged input is never resent.";
        Notify();
    }

    public async Task SendInputAsync(string data)
    {
        if (!CanType || string.IsNullOrEmpty(data)) return;
        if (data.Length > 8_192 || _pendingInput >= 32)
        {
            Block("Input queue limit reached. Input was not resent. Reconnect and inspect the prompt before typing.");
            return;
        }
        var generation = _generation;
        var inputEpoch = _inputEpoch;
        _pendingInput++;
        await _inputGate.WaitAsync();
        try
        {
            if (generation != _generation || inputEpoch != _inputEpoch || _blocked || Status != "running" || _connection is null || CurrentJobId is null) return;
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
            await client.WriteProjectTerminalAsync(_connection, Folder, CurrentJobId, data, timeout.Token);
        }
        catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
        {
            if (generation == _generation)
                Block("Input delivery is uncertain; typing is disabled. Reconnect and inspect the prompt before entering anything again. Input is never automatically retried.");
        }
        finally
        {
            _pendingInput--;
            _inputGate.Release();
        }
    }

    public async Task ResizeAsync(int columns, int rows)
    {
        if (!CanType || _connection is null || CurrentJobId is null) return;
        _pendingResize = (Math.Clamp(columns, 20, 500), Math.Clamp(rows, 5, 200));
        if (_resizing) return;
        var generation = _generation;
        _resizing = true;
        try
        {
            while (generation == _generation && CanType && _pendingResize is { } size)
            {
                _pendingResize = null;
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                await client.ResizeProjectTerminalAsync(_connection, Folder, CurrentJobId!,
                    size.Columns, size.Rows, timeout.Token);
            }
        }
        catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
        {
            if (generation == _generation)
                Block("Terminal resize failed or the API connection changed. Reconnect before typing.");
        }
        finally { _resizing = false; }
    }

    private async Task PollAsync(CancellationTokenSource source, int generation, Func<string, bool, Task> render)
    {
        while (IsCurrent(source, generation) && !_blocked)
        {
            try
            {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(source.Token);
                timeout.CancelAfter(TimeSpan.FromSeconds(8));
                var response = await client.ReadProjectTerminalAsync(_connection!, Folder, CurrentJobId!, _cursor, timeout.Token);
                if (!IsCurrent(source, generation)) return;
                if (!response.Reset && response.Output.Length > 0 && response.NextCursor == _cursor)
                    throw new InvalidDataException("Output cursor did not advance.");
                if (response.Reset)
                {
                    _buffer.Clear();
                    _filter.Reset();
                    _historyTruncated = true;
                }
                var output = _filter.Filter(response.Output);
                _buffer.Append(output);
                if (_buffer.Length > BufferLimit)
                {
                    _buffer.Remove(0, _buffer.Length - BufferLimit);
                    _historyTruncated = true;
                }
                _cursor = response.NextCursor;
                Status = response.Status;
                Notice = _historyTruncated
                    ? "Earlier scrollback expired or exceeded the memory limit; showing retained output only."
                    : IsRunning
                        ? "Live PTY · input goes only to this deployment job · Ctrl+C interrupts it · closing the panel leaves it running."
                        : _catalogJob is not null
                            ? "Process ended. Exit status is not proof of Azure deployment; reload catalog jobs and verify the exact Azure scope separately."
                            : "Process ended. Exit status is not proof of Azure deployment; verify live resources on the board.";
                if (output.Length > 0 || response.Reset) await render(output, response.Reset);
                if (!IsCurrent(source, generation)) return;
                Notify();
                // Drain all retained chunks even after the process has ended.
                if (!IsRunning && response.Output.Length == 0) return;
                await Task.Delay(150, source.Token);
            }
            catch (OperationCanceledException) when (source.IsCancellationRequested) { return; }
            catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
            {
                if (!IsCurrent(source, generation)) return;
                var expired = exception is ApiRequestException api &&
                    api.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Gone;
                Block(expired
                    ? "This job's terminal is unavailable or its in-memory output expired (for example after an API restart). No historical output was fabricated."
                    : "Terminal connection lost, expired, or changed. Typing is disabled. Restore the original API connection and select Reconnect.");
                return;
            }
        }
    }

    private bool IsCurrent(CancellationTokenSource source, int generation) =>
        !source.IsCancellationRequested && _reading == source && generation == _generation;

    private void Block(string notice)
    {
        _blocked = true;
        _inputEpoch++;
        Notice = notice;
        StopReading();
        Notify();
    }

    private void StopReading()
    {
        _reading?.Cancel();
        _reading = null;
    }

    private void Notify() => Changed?.Invoke(this, EventArgs.Empty);
}
