using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public readonly record struct RelativeMapPoint(double X, double Y);
public readonly record struct MapViewport(double X, double Y, double Width, double Height);
public sealed record MapMarkerPosition(AzureRegionInfo Region, RelativeMapPoint Anchor, RelativeMapPoint Center);

public static class RegionMapPresentation
{
    // Must match the offline Natural Earth SVG projection.
    public const double MapNorth = 85;
    public const double MapSouth = -60;
    public const double MapAspectRatio = 360d / (MapNorth - MapSouth);

    public static bool IsGeographicRegion(AzureRegionInfo region) =>
        !string.Equals(region.Name, "global", StringComparison.OrdinalIgnoreCase);

    public static bool CanCloneConfiguration(AzureRegionInfo? region, string primaryRegion) =>
        region is not null && IsGeographicRegion(region) && !string.IsNullOrWhiteSpace(primaryRegion) &&
        !region.Name.Equals(primaryRegion, StringComparison.OrdinalIgnoreCase);

    public static MapViewport FitViewport(double width, double height)
    {
        if (!double.IsFinite(width) || !double.IsFinite(height) || width <= 0 || height <= 0)
        {
            return new MapViewport(0, 0, 0, 0);
        }

        var mapWidth = Math.Min(width, height * MapAspectRatio);
        var mapHeight = mapWidth / MapAspectRatio;
        return new MapViewport(0, 0, mapWidth, mapHeight);
    }

    public static RelativeMapPoint ProjectRegion(double longitude, double latitude)
    {
        if (!double.IsFinite(longitude) || !double.IsFinite(latitude))
        {
            throw new ArgumentException("Region coordinates must be finite.");
        }

        return new RelativeMapPoint(
            (Math.Clamp(longitude, -180, 180) + 180) / 360,
            (MapNorth - Math.Clamp(latitude, MapSouth, MapNorth)) / (MapNorth - MapSouth));
    }

    public static IReadOnlyList<MapMarkerPosition> PositionMarkers(
        IEnumerable<AzureRegionInfo> regions, double width, double height)
    {
        ArgumentNullException.ThrowIfNull(regions);
        if (width < 32 || height < 32)
        {
            return [];
        }

        const double separation = 22;
        var result = new List<MapMarkerPosition>();
        // Place configured regions first; the remaining markers fan out around their real anchors.
        foreach (var region in regions.Where(IsGeographicRegion).OrderByDescending(region => region.HasFactory)
                     .ThenBy(region => region.Name, StringComparer.Ordinal))
        {
            var projected = ProjectRegion(region.Longitude, region.Latitude);
            var anchor = new RelativeMapPoint(projected.X * width, projected.Y * height);
            var center = ClampCenter(anchor, width, height);
            for (var attempt = 0; attempt < 600; attempt++)
            {
                var angle = attempt * 2.399963229728653;
                var radius = attempt == 0 ? 0 : 5 * Math.Sqrt(attempt);
                center = ClampCenter(
                    new RelativeMapPoint(anchor.X + Math.Cos(angle) * radius,
                        anchor.Y + Math.Sin(angle) * radius), width, height);
                if (result.All(placed =>
                        Math.Pow(placed.Center.X - center.X, 2) +
                        Math.Pow(placed.Center.Y - center.Y, 2) >= separation * separation))
                {
                    break;
                }
            }

            result.Add(new MapMarkerPosition(region, anchor, center));
        }

        return result;
    }

    private static RelativeMapPoint ClampCenter(RelativeMapPoint point, double width, double height) =>
        new(Math.Clamp(point.X, 16, width - 16), Math.Clamp(point.Y, 16, height - 16));

    public static RelativeMapPoint MapCoordinates(
        double longitude,
        double latitude,
        double padding = 0.04)
    {
        padding = Math.Clamp(padding, 0, 0.49);
        longitude = Math.Clamp(longitude, -180, 180);
        latitude = Math.Clamp(latitude, -90, 90);
        var usable = 1 - (padding * 2);
        return new RelativeMapPoint(
            padding + (((longitude + 180) / 360) * usable),
            padding + (((90 - latitude) / 180) * usable));
    }

    public static RelativeMapPoint MapNormalizedCoordinates(
        double normalizedLongitude,
        double normalizedLatitude,
        double padding = 0.04) =>
        MapCoordinates(
            Math.Clamp(normalizedLongitude, -1, 1) * 180,
            Math.Clamp(normalizedLatitude, -1, 1) * 90,
            padding);

    public static bool CanDelete(AzureRegionInfo? region) =>
        region?.HasFactory == true;

    public static bool CanClone(
        AzureRegionInfo? selectedRegion,
        IReadOnlyList<string>? activeRegions) =>
        selectedRegion is { HasFactory: false } &&
        SelectCloneSource(selectedRegion, activeRegions) is not null;

    public static string? SelectCloneSource(
        AzureRegionInfo? selectedRegion,
        IReadOnlyList<string>? activeRegions)
    {
        return activeRegions?
            .FirstOrDefault(region =>
                !string.IsNullOrWhiteSpace(region) &&
                !string.Equals(
                    region,
                    selectedRegion?.Name,
                    StringComparison.OrdinalIgnoreCase));
    }
}
