using System.Text.Json;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed class SavedConfigurationVerifier(
    IProjectVerificationClient projects, IScaleSetVerificationClient scaleSets)
{
    private CancellationTokenSource? _cancellation;

    public void Cancel() => _cancellation?.Cancel();

    public async Task<bool> VerifyAsync(
        IList<SavedConfigurationItemViewModel> items, Func<string> currentFolder)
    {
        Cancel();
        using var cancellation = new CancellationTokenSource();
        _cancellation = cancellation;
        var folder = currentFolder();
        try
        {
            foreach (var item in items.ToArray())
            {
                if (cancellation.IsCancellationRequested)
                {
                    return false;
                }
                if (!item.HasResourceGroupLink || !FactoryNetworkSession.SameFolder(item.Folder, folder))
                {
                    item.SetVerificationUnavailable(item.ResourceGroupLinkHint);
                    continue;
                }
                item.SetVerificationPending();
                try
                {
                    Action apply;
                    if (item.Project is { } project)
                    {
                        var result = await projects.VerifyProjectResourceGroupsAsync(
                            folder, project.ProjectNumber, item.Path, cancellation.Token);
                        apply = () => item.ApplyVerification(result);
                    }
                    else if (item.ScaleSet is { } scaleSet)
                    {
                        var result = await scaleSets.VerifyScaleSetResourceGroupsAsync(
                            folder, scaleSet.ScaleSetId, item.Path, cancellation.Token);
                        apply = () => item.ApplyVerification(result);
                    }
                    else
                    {
                        throw new InvalidOperationException("Saved configuration has no project or scale-set identity.");
                    }
                    if (!cancellation.IsCancellationRequested && items.Contains(item) &&
                        FactoryNetworkSession.SameFolder(folder, currentFolder()))
                    {
                        apply();
                    }
                }
                catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
                {
                    return false;
                }
                catch (Exception exception) when (exception is HttpRequestException or IOException or JsonException or
                    InvalidOperationException or ArgumentException or OperationCanceledException)
                {
                    if (!cancellation.IsCancellationRequested && items.Contains(item) &&
                        FactoryNetworkSession.SameFolder(folder, currentFolder()))
                    {
                        item.SetVerificationUnavailable($"Resource group validation failed: {exception.Message}");
                    }
                }
            }
            return !cancellation.IsCancellationRequested;
        }
        finally
        {
            if (ReferenceEquals(_cancellation, cancellation))
            {
                _cancellation = null;
            }
        }
    }
}
