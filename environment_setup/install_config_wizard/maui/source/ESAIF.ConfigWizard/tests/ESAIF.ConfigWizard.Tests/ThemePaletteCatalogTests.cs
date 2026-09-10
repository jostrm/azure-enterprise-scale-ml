using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ThemePaletteCatalogTests
{
    [Fact]
    public void Palettes_ExposeTheSameSemanticTokens()
    {
        Assert.Equal(
            ThemePaletteCatalog.Light.Colors.Keys.Order(),
            ThemePaletteCatalog.Dark.Colors.Keys.Order());
    }

    [Theory]
    [InlineData("Text", "Canvas", 7.0)]
    [InlineData("Text", "Surface", 7.0)]
    [InlineData("Muted", "Canvas", 4.5)]
    [InlineData("PrimaryStrong", "Surface", 4.5)]
    public void LightPalette_TextMeetsContrastTarget(
        string foreground,
        string background,
        double minimumRatio)
    {
        Assert.True(
            ContrastRatio(
                ThemePaletteCatalog.Light.Colors[foreground],
                ThemePaletteCatalog.Light.Colors[background]) >= minimumRatio);
    }

    [Theory]
    [InlineData("Text", "Canvas", 7.0)]
    [InlineData("Text", "Surface", 7.0)]
    [InlineData("Muted", "Canvas", 4.5)]
    [InlineData("PrimaryStrong", "Surface", 4.5)]
    public void DarkPalette_TextMeetsContrastTarget(
        string foreground,
        string background,
        double minimumRatio)
    {
        Assert.True(
            ContrastRatio(
                ThemePaletteCatalog.Dark.Colors[foreground],
                ThemePaletteCatalog.Dark.Colors[background]) >= minimumRatio);
    }

    [Fact]
    public void DarkPalette_UsesDistinctLowGlareSurfaces()
    {
        Assert.NotEqual(
            ThemePaletteCatalog.Light.Colors["Canvas"],
            ThemePaletteCatalog.Dark.Colors["Canvas"]);
        Assert.NotEqual(
            ThemePaletteCatalog.Dark.Colors["Canvas"],
            ThemePaletteCatalog.Dark.Colors["Surface"]);
        Assert.NotEqual(
            ThemePaletteCatalog.Dark.Colors["Surface"],
            ThemePaletteCatalog.Dark.Colors["SurfaceMuted"]);
    }

    private static double ContrastRatio(string foreground, string background)
    {
        var foregroundLuminance = RelativeLuminance(foreground);
        var backgroundLuminance = RelativeLuminance(background);
        var lighter = Math.Max(foregroundLuminance, backgroundLuminance);
        var darker = Math.Min(foregroundLuminance, backgroundLuminance);
        return (lighter + 0.05) / (darker + 0.05);
    }

    private static double RelativeLuminance(string hex)
    {
        var value = hex.TrimStart('#');
        var red = Convert.ToInt32(value[..2], 16) / 255d;
        var green = Convert.ToInt32(value[2..4], 16) / 255d;
        var blue = Convert.ToInt32(value[4..6], 16) / 255d;
        return 0.2126 * Linearize(red) +
               0.7152 * Linearize(green) +
               0.0722 * Linearize(blue);
    }

    private static double Linearize(double channel)
    {
        return channel <= 0.04045
            ? channel / 12.92
            : Math.Pow((channel + 0.055) / 1.055, 2.4);
    }
}
