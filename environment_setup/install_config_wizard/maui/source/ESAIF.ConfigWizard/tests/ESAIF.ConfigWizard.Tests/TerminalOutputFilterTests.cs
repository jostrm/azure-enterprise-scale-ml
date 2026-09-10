using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class TerminalOutputFilterTests
{
    [Fact]
    public void KeepsAnsiAndExactPromptBytesAcrossChunkBoundaries()
    {
        var filter = new TerminalOutputFilter();
        Assert.Equal("hello ", filter.Filter("hello \x1b"));
        Assert.Equal("\x1b[31m", filter.Filter("[31m"));
        Assert.Equal("\r\nPrompt> \t", filter.Filter("\r\nPrompt> \t"));
    }

    [Theory]
    [InlineData("\x1b]52;c;clipboard\a")]
    [InlineData("\x1b]8;;https://outside.invalid\x1b\\")]
    [InlineData("\x1bPdevice-control\x1b\\")]
    [InlineData("\x1b_private-control\x1b\\")]
    [InlineData("\u009d52;c;clipboard\u009c")]
    public void RemovesStringControlsAtEveryPossibleSplit(string control)
    {
        for (var split = 0; split <= control.Length; split++)
        {
            var filter = new TerminalOutputFilter();
            Assert.Equal("beforeafter", filter.Filter("before" + control[..split]) + filter.Filter(control[split..] + "after"));
        }
    }

    [Fact]
    public void ResetDropsPartialControlState()
    {
        var filter = new TerminalOutputFilter();
        Assert.Equal(string.Empty, filter.Filter("\x1b]52;"));
        filter.Reset();
        Assert.Equal("visible", filter.Filter("visible"));
    }
}
