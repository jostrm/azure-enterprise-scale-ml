using System.Globalization;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public static class RegionPipelinePresentation
{
    public const string FailureColor = "#FF7185";

    public static bool HasFailure(AzureRegionInfo? region) =>
        region?.PipelineFindings.Any(finding => finding.Status == "failed") == true;

    public static string LightColor(AzureRegionInfo region, bool selected) =>
        HasFailure(region) ? FailureColor : selected ? "#FFD48A" : region.HasFactory ? "#61F3B1" : "#79DCED";

    public static string Tooltip(AzureRegionInfo region) =>
        $"{region.DisplayName} ({region.Name})" +
        (string.IsNullOrWhiteSpace(region.CountDetails) ? string.Empty : $"\n{region.CountDetails}") +
        (HasFailure(region) ? $"\n\n{Details(region)}" : string.Empty);

    public static string Details(AzureRegionInfo? region)
    {
        if (!HasFailure(region))
        {
            return string.Empty;
        }
        var findings = region!.PipelineFindings.Where(finding => finding.Status == "failed")
            .Select(FormatFinding);
        return "LAST-RUN FINDINGS - not live Azure capacity or service health.\n\n" +
               string.Join("\n\n", findings) +
               "\n\nRe-run the relevant check or deployment to confirm availability. An unrelated successful run does not clear this finding.";
    }

    private static string FormatFinding(RegionPipelineFinding finding)
    {
        var source = finding.Source == "user_reported" ? "User-reported pipeline result" : "Pipeline report";
        var skus = finding.Skus.Count > 0 ? $"\nAffected SKUs: {string.Join(", ", finding.Skus)}" : string.Empty;
        var environment = string.IsNullOrWhiteSpace(finding.Environment)
            ? "\nEnvironment: not provided" : $"\nEnvironment: {finding.Environment}";
        var run = string.IsNullOrWhiteSpace(finding.RunId) ? "\nRun ID: not provided" : $"\nRun ID: {finding.RunId}";
        var observed = DateTimeOffset.TryParse(finding.ObservedAt, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal, out var timestamp)
            ? timestamp.ToUniversalTime().ToString("yyyy-MM-dd HH:mm 'UTC'", CultureInfo.InvariantCulture)
            : "not provided";
        var link = string.IsNullOrWhiteSpace(finding.RunUrl) ? string.Empty : $"\nRun link: {finding.RunUrl}";
        var service = finding.Service.Equals("microsoft.search/searchservices", StringComparison.OrdinalIgnoreCase)
            ? "Azure AI Search" : finding.Service;
        return $"{service} - {KindLabel(finding.Kind)}{skus}\n{finding.Message}\nSource: {source}{environment}{run}\nRun time: {observed}{link}";
    }

    private static string KindLabel(string kind) => kind switch
    {
        "capacity" => "SKU capacity/availability finding",
        "quota" => "quota finding",
        "pipeline_error" => "pipeline failure",
        _ => "pre-flight failure"
    };
}
