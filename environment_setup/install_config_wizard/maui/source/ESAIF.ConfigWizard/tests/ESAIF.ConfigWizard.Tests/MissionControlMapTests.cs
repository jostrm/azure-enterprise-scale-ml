using System.Xml.Linq;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class MissionControlMapTests
{
    [Theory]
    [InlineData(1440, 580)]
    [InlineData(600, 600)]
    [InlineData(1900, 400)]
    public void Viewport_PreservesGeographicAspectRatioAndAnchorsTopLeft(double width, double height)
    {
        var viewport = RegionMapPresentation.FitViewport(width, height);
        Assert.Equal(RegionMapPresentation.MapAspectRatio, viewport.Width / viewport.Height, 8);
        Assert.Equal(0, viewport.X);
        Assert.Equal(0, viewport.Y);
        Assert.InRange(viewport.Width, 0, width);
        Assert.InRange(viewport.Height, 0, height);
    }

    [Theory]
    [InlineData(-180, 85, 0, 0)]
    [InlineData(180, -60, 1, 1)]
    [InlineData(0, 12.5, .5, .5)]
    [InlineData(-78.39, 36.67, .28225, .3333103448275862)]
    public void Projection_MatchesBasemap(double longitude, double latitude, double x, double y)
    {
        var actual = RegionMapPresentation.ProjectRegion(longitude, latitude);
        Assert.Equal(x, actual.X, 7);
        Assert.Equal(y, actual.Y, 7);
    }

    [Fact]
    public void Projection_RejectsNonFiniteCoordinates()
    {
        Assert.Throws<ArgumentException>(() => RegionMapPresentation.ProjectRegion(double.NaN, 40));
        Assert.Throws<ArgumentException>(() => RegionMapPresentation.ProjectRegion(30, double.PositiveInfinity));
        Assert.Equal(new MapViewport(0, 0, 0, 0), RegionMapPresentation.FitViewport(-1, 400));
    }

    [Fact]
    public void ColocatedMarkers_RemainIndividuallySelectableAndPreserveAnchors()
    {
        var regions = new[]
        {
            new AzureRegionInfo { Name = "australiacentral", Longitude = 149.13, Latitude = -35.28, HasFactory = true },
            new AzureRegionInfo { Name = "australiacentral2", Longitude = 149.13, Latitude = -35.28 },
            new AzureRegionInfo { Name = "nearby", Longitude = 149.2, Latitude = -35.3 }
        };
        var positions = RegionMapPresentation.PositionMarkers(regions, 1200, 483);
        Assert.Equal(3, positions.Count);
        Assert.Equal(positions[0].Anchor, positions[1].Anchor);
        foreach (var first in positions)
        {
            Assert.InRange(first.Center.X, 16, 1184);
            Assert.InRange(first.Center.Y, 16, 467);
            foreach (var second in positions.Where(position => position.Region != first.Region))
            {
                var distance = Math.Sqrt(Math.Pow(first.Center.X - second.Center.X, 2) +
                                         Math.Pow(first.Center.Y - second.Center.Y, 2));
                Assert.True(distance >= 22);
            }
        }

        Assert.Equal(positions, RegionMapPresentation.PositionMarkers(regions.Reverse(), 1200, 483));
    }

    [Fact]
    public void CloneConfiguration_UsesSourcePrimaryRegionNotInventoryPresence()
    {
        Assert.True(RegionMapPresentation.CanCloneConfiguration(
            new AzureRegionInfo { Name = "swedencentral", HasFactory = true }, "eastus2"));
        Assert.False(RegionMapPresentation.CanCloneConfiguration(
            new AzureRegionInfo { Name = "eastus2", HasFactory = true }, "eastus2"));
        Assert.False(RegionMapPresentation.CanCloneConfiguration(
            new AzureRegionInfo { Name = "global" }, "eastus2"));
    }

    [Fact]
    public void GlobalServiceScope_IsNotPlottedAsAnAtlanticDatacenter()
    {
        var regions = new[]
        {
            new AzureRegionInfo { Name = "global", HasFactory = true },
            new AzureRegionInfo { Name = "swedencentral", Longitude = 17.14, Latitude = 60.67 }
        };
        var positions = RegionMapPresentation.PositionMarkers(regions, 1440, 580);
        Assert.Single(positions);
        Assert.Equal("swedencentral", positions[0].Region.Name);
    }

    [Fact]
    public void Basemap_ContainsRealCountryGeometryAndProjectionMetadata()
    {
        var document = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "world_map.svg"));
        XNamespace ns = "http://www.w3.org/2000/svg";
        var root = document.Root!;
        Assert.Equal("0 0 1440 580", (string?)root.Attribute("viewBox"));
        Assert.Contains("latitude 85..-60", root.Element(ns + "desc")!.Value);
        Assert.Contains("Natural Earth", root.Element(ns + "desc")!.Value);
        var countries = root.Elements(ns + "g").Single(group => (string?)group.Attribute("id") == "countries")
            .Elements(ns + "path").ToArray();
        Assert.True(countries.Length >= 170);
        Assert.Contains(countries, path => (string?)path.Attribute("data-country") == "Sweden");
        Assert.Contains(countries, path => (string?)path.Attribute("data-country") == "Australia");
        Assert.All(countries, path => Assert.True(((string?)path.Attribute("d"))?.Length > 20));
    }
}
