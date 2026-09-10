using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Tests;

public sealed class OperationViewModelTests
{
    [Fact]
    public async Task ExecuteOperationAsync_SurfacesInvalidFileWithoutThrowing()
    {
        var viewModel = new TestOperationViewModel();

        await viewModel.RunAsync(
            new InvalidDataException("Select a supported configuration file."));

        Assert.Equal(
            "Select a supported configuration file.",
            viewModel.StatusMessage);
        Assert.False(viewModel.IsBusy);
    }

    [Fact]
    public async Task ExecuteOperationAsync_SurfacesTimeoutGuidance()
    {
        var viewModel = new TestOperationViewModel();

        await viewModel.RunAsync(new TaskCanceledException());

        Assert.Contains("timed out", viewModel.StatusMessage);
        Assert.False(viewModel.IsBusy);
    }

    private sealed class TestOperationViewModel : OperationViewModel
    {
        public Task RunAsync(Exception exception)
        {
            return ExecuteOperationAsync(
                () => Task.FromException(exception),
                "Working...");
        }
    }
}
