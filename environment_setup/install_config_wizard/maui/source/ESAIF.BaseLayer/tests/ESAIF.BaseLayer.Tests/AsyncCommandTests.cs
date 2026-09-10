using ESAIF.BaseLayer.Application;

namespace ESAIF.BaseLayer.Tests;

public sealed class AsyncCommandTests
{
    [Fact]
    public async Task Execute_DisablesCommandUntilOperationCompletes()
    {
        var completion = new TaskCompletionSource(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var started = new TaskCompletionSource(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var command = new AsyncCommand(async () =>
        {
            started.SetResult();
            await completion.Task;
        });

        command.Execute(null);
        await started.Task;

        Assert.False(command.CanExecute(null));

        completion.SetResult();
        await Task.Delay(20);
        Assert.True(command.CanExecute(null));
    }

    [Fact]
    public async Task Execute_RaisesExecutionFailedWhenHandled()
    {
        var failure = new TaskCompletionSource<Exception>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var command = new AsyncCommand(
            () => Task.FromException(new InvalidOperationException("failed")));
        command.ExecutionFailed += (_, exception) => failure.SetResult(exception);

        command.Execute(null);
        var exception = await failure.Task;

        Assert.IsType<InvalidOperationException>(exception);
        Assert.Equal("failed", exception.Message);
    }
}
