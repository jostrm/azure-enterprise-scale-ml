using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Tests;

public sealed class RecentProjectChoiceTests
{
    [Fact]
    public void Create_IncludesProjectScaleSetAndFolder()
    {
        var project = new RecentProject
        {
            Folder = @"C:\work\aifactory",
            Project = "007",
            Orchestrator = "ado",
            PrefixResourceGroup = "demo-",
            SuffixResourceGroup = "-003"
        };

        var choice = RecentProjectChoice.Create(2, project);

        Assert.Equal(
            @"2. Project 007 (demo-003) - C:\work\aifactory",
            choice.Title);
        Assert.Same(project, choice.Project);
        Assert.Equal("2. Project 007 (demo-003)", choice.SelectionLabel);
        Assert.DoesNotContain(project.Folder, choice.SelectionLabel);
    }

    [Fact]
    public void Create_OmitsEmptyScaleSetIdentity()
    {
        var choice = RecentProjectChoice.Create(1, new RecentProject
        {
            Folder = @"C:\aifactory",
            Project = "001",
            Orchestrator = "gha"
        });

        Assert.Equal(
            @"1. Project 001 - C:\aifactory",
            choice.Title);
        Assert.Equal("1. Project 001", choice.SelectionLabel);
    }

    [Fact]
    public void SameProjectInDifferentFoldersKeepsDistinctChoiceAndOriginalIdentity()
    {
        var first = RecentProjectChoice.Create(1, new() { Folder = @"C:\one\aifactory", Project = "001" });
        var second = RecentProjectChoice.Create(2, new() { Folder = @"C:\two\aifactory", Project = "001" });
        Assert.NotEqual(first.SelectionLabel, second.SelectionLabel);
        Assert.Equal(@"C:\one\aifactory", first.Project.Folder);
        Assert.Equal(@"C:\two\aifactory", second.Project.Folder);
    }
}
