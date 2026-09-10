using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class TerminalFailurePolicyTests
{
    [Fact]
    public void RecognizesExpectedTransportAndLifecycleFailures()
    {
        Assert.True(TerminalFailurePolicy.IsExpected(new HttpRequestException()));
        Assert.True(TerminalFailurePolicy.IsExpected(new InvalidDataException()));
        Assert.True(TerminalFailurePolicy.IsExpected(new OperationCanceledException()));
        Assert.True(TerminalFailurePolicy.IsExpected(new ProjectTerminalConnectionException("Connection changed.")));
        Assert.True(TerminalFailurePolicy.IsExpected(new TerminalUnavailableException("Renderer closed.")));
    }

    [Fact]
    public void DoesNotSwallowProgrammingErrorsAsConnectionFailures()
    {
        Assert.False(TerminalFailurePolicy.IsExpected(new NullReferenceException()));
        Assert.False(TerminalFailurePolicy.IsExpected(new IndexOutOfRangeException()));
        Assert.False(TerminalFailurePolicy.IsExpected(new ArgumentException()));
        Assert.False(TerminalFailurePolicy.IsExpected(new InvalidOperationException()));
    }
}
