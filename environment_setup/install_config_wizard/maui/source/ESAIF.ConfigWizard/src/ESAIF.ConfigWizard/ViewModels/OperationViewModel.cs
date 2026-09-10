using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.BaseLayer.Networking;

namespace ESAIF.ConfigWizard.ViewModels;

public abstract class OperationViewModel : ObservableObject
{
    private bool _isBusy;
    private string _statusMessage = string.Empty;
    private string _warning = string.Empty;
    private string _errorMessage = string.Empty;

    public string Warning
    {
        get => _warning;
        protected set
        {
            if (SetProperty(ref _warning, value))
            {
                OnPropertyChanged(nameof(HasWarning));
            }
        }
    }

    public bool HasWarning => !string.IsNullOrWhiteSpace(Warning);

    public string ErrorMessage
    {
        get => _errorMessage;
        private set => SetProperty(ref _errorMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                OnPropertyChanged(nameof(IsNotBusy));
            }
        }
    }

    public bool IsNotBusy => !IsBusy;

    public string StatusMessage
    {
        get => _statusMessage;
        protected set => SetProperty(ref _statusMessage, value);
    }

    protected async Task ExecuteOperationAsync(
        Func<Task> operation,
        string progressMessage)
    {
        if (IsBusy)
        {
            return;
        }

        IsBusy = true;
        ErrorMessage = string.Empty;
        StatusMessage = progressMessage;
        try
        {
            await operation();
        }
        catch (TaskCanceledException exception)
        {
            OnOperationFailed(exception);
            StatusMessage = "The API request timed out. Confirm the Python API is running.";
            ErrorMessage = StatusMessage;
        }
        catch (Exception exception) when (
            exception is ApiRequestException or
            HttpRequestException or
            ArgumentException or
            InvalidOperationException or
            InvalidDataException or
            NotSupportedException or
            IOException or
            UnauthorizedAccessException or
            JsonException)
        {
            OnOperationFailed(exception);
            StatusMessage = exception.Message;
            ErrorMessage = StatusMessage;
        }
        finally
        {
            IsBusy = false;
        }
    }

    protected virtual void OnOperationFailed(Exception exception)
    {
    }
}
