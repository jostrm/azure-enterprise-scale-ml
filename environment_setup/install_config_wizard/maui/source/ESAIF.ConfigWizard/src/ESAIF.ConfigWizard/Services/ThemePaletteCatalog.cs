namespace ESAIF.ConfigWizard.Services;

public sealed record ThemePalette(
    IReadOnlyDictionary<string, string> Colors,
    string HeroStart,
    string HeroMiddle,
    string HeroEnd);

public static class ThemePaletteCatalog
{
    public static ThemePalette Light { get; } = new(
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Primary"] = "#6750A4",
            ["PrimaryStrong"] = "#4F378B",
            ["Secondary"] = "#0F6CBD",
            ["Accent"] = "#006B75",
            ["Canvas"] = "#F7F6FA",
            ["Surface"] = "#FFFFFF",
            ["SurfaceMuted"] = "#F0EEF4",
            ["SurfaceSelected"] = "#EEE8FF",
            ["Border"] = "#E1DDE7",
            ["Text"] = "#24212A",
            ["Muted"] = "#686370",
            ["Success"] = "#0F7B55",
            ["SuccessSurface"] = "#E1F3EA",
            ["Warning"] = "#9A6700",
            ["Danger"] = "#C42B1C",
            ["Flyout"] = "#29272F",
            ["White"] = "#FFFFFF",
            ["Black"] = "#000000",
            ["Gray100"] = "#F0EEF4",
            ["Gray200"] = "#E1DDE7",
            ["Gray500"] = "#686370",
            ["Gray900"] = "#24212A"
        },
        HeroStart: "#352F5B",
        HeroMiddle: "#6750A4",
        HeroEnd: "#006B75");

    public static ThemePalette Dark { get; } = new(
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Primary"] = "#B9A7FF",
            ["PrimaryStrong"] = "#D8CEFF",
            ["Secondary"] = "#78B9F4",
            ["Accent"] = "#62D4D8",
            ["Canvas"] = "#121016",
            ["Surface"] = "#1B1820",
            ["SurfaceMuted"] = "#27232D",
            ["SurfaceSelected"] = "#382E50",
            ["Border"] = "#403A48",
            ["Text"] = "#F5F1F7",
            ["Muted"] = "#BDB5C5",
            ["Success"] = "#69D3A6",
            ["SuccessSurface"] = "#173A2E",
            ["Warning"] = "#F3C969",
            ["Danger"] = "#FF8A7E",
            ["Flyout"] = "#0D0C10",
            ["White"] = "#FFFFFF",
            ["Black"] = "#000000",
            ["Gray100"] = "#27232D",
            ["Gray200"] = "#403A48",
            ["Gray500"] = "#BDB5C5",
            ["Gray900"] = "#F5F1F7"
        },
        HeroStart: "#171326",
        HeroMiddle: "#4F378B",
        HeroEnd: "#004E57");
}
