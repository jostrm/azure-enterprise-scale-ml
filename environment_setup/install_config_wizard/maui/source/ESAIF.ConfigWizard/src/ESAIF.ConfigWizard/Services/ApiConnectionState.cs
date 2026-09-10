using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.Services;

public enum ApiConnectionStatus { Unverified, Verifying, Connected, Disconnected }

public sealed class ApiConnectionState : ObservableObject
{
    public ApiConnectionStatus Status { get; private set; }
    public DateTimeOffset? LastVerifiedAt { get; private set; }
    public string LastError { get; private set; } = string.Empty;
    public bool IsConnected => Status == ApiConnectionStatus.Connected;
    public string Label => Status switch
    {
        ApiConnectionStatus.Connected => "API connected · last verified",
        ApiConnectionStatus.Verifying => "Verifying API connection",
        ApiConnectionStatus.Disconnected => "API disconnected",
        _ => "API not verified"
    };
    public string ColorHex => Status switch
    {
        ApiConnectionStatus.Connected => "#22C9A7",
        ApiConnectionStatus.Disconnected => "#E45664",
        _ => "#D79B32"
    };

    public void BeginVerification() => Update(ApiConnectionStatus.Verifying);

    public void MarkVerified()
    {
        LastVerifiedAt = DateTimeOffset.UtcNow;
        LastError = string.Empty;
        Update(ApiConnectionStatus.Connected);
    }

    public void MarkFailed(Exception exception)
    {
        ArgumentNullException.ThrowIfNull(exception);
        LastError = exception.Message;
        Update(ApiConnectionStatus.Disconnected);
    }

    private void Update(ApiConnectionStatus status)
    {
        Status = status;
        OnPropertyChanged(nameof(Status));
        OnPropertyChanged(nameof(IsConnected));
        OnPropertyChanged(nameof(Label));
        OnPropertyChanged(nameof(ColorHex));
        OnPropertyChanged(nameof(LastVerifiedAt));
        OnPropertyChanged(nameof(LastError));
    }
}
