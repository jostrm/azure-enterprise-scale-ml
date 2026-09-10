using System.Text.RegularExpressions;

namespace ESAIF.ConfigWizard.Services;

/// <summary>Presentation only. Never use these summaries in configuration or API payloads.</summary>
public static partial class TechnicalValuePresentation
{
    // Include N, D, B, P and X GUID formats; do not leave recognizable GUID fragments behind.
    [GeneratedRegex(@"(?i)\{0x[0-9a-f]{8},\s*0x[0-9a-f]{4},\s*0x[0-9a-f]{4},\s*\{(?:0x[0-9a-f]{2},\s*){7}0x[0-9a-f]{2}\}\}|[\{\(]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[\}\)]?|(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")]
    private static partial Regex GuidPattern();

    // Quoted paths keep spaces. An unquoted local path consumes the rest of its line:
    // hiding a little surrounding prose is preferable to exposing part of a file path.
    [GeneratedRegex("""
        (?ix)
        ["'](?:[a-z]:[\\/]|\\\\|//|file:/|~/|\.\.?[\\/]|/(?!/))[^"'\r\n]*["']
        |(?<![\w:/])[a-z]:[\\/][^\r\n"'<>|]*
        |(?<![\w:/])(?:\\\\|file:/|~/|\.\.?[\\/])[^\r\n"'<>|]*
        |(?<![\w:/])/(?!/)[a-z0-9_.-]+(?:/[^\r\n"'<>|]*)?
        |(?<![\w:/])//[a-z0-9_.-]+/[^\r\n"'<>|]*
        |(?<![\w:/])(?:[\w.-]+[\\/])+(?:[\w .-]+\.(?:py|sh|ps1|json|ya?ml|env|cs|xaml|txt|log|csv|zip|pem|pfx))(?!\w)
        """)]
    private static partial Regex PathPattern();

    [GeneratedRegex(@"(?i)\b(?:https?|wss?|ssh|git)://[^\s<>""']+")]
    private static partial Regex NetworkUrlPattern();

    [GeneratedRegex(@"(?i)(?:password|passwd|api[_ -]?key|secret|(?:access|refresh|auth|bearer)[_ -]?token|private[_ -]?key|(?:^|[_ -])pat(?:$|[_ -])|credential)")]
    private static partial Regex SecretPattern();

    [GeneratedRegex(@"(?i)(?:env(?:ironment)?(?:[_ -]?variable)?$|secret[_ -]?(?:id|uri|url)$)")]
    private static partial Regex SecretReferencePattern();

    [GeneratedRegex(@"(?i)(?:^|[_ -])(?:path|folder|directory)(?:$|[_ -])|(?:^|[_ -])file(?:[_ -]?name)?$|(?-i:Path|Folder|Directory|FileName|File)$")]
    private static partial Regex LocalFieldPattern();

    public static bool IsLocalField(string? context) =>
        !string.IsNullOrWhiteSpace(context) && LocalFieldPattern().IsMatch(context);

    public static bool IsSecret(string? context) =>
        !string.IsNullOrEmpty(context) && SecretPattern().IsMatch(context) &&
        !SecretReferencePattern().IsMatch(context);

    public static string Summary(string? value, string? caption = null, bool conceal = false)
    {
        if (string.IsNullOrEmpty(value)) return string.Empty;
        if (conceal) return SafeCaption(caption);
        // Protect ordinary network URLs from path detection, but still conceal GUIDs in them.
        var urls = new List<string>();
        var text = NetworkUrlPattern().Replace(value, match =>
        {
            urls.Add(match.Value);
            return $"\u0001{urls.Count - 1}\u0002";
        });
        text = PathPattern().Replace(text, "[local path]");
        for (var index = 0; index < urls.Count; index++)
            text = text.Replace($"\u0001{index}\u0002", urls[index], StringComparison.Ordinal);
        text = GuidPattern().Replace(text, "[id]");
        if (text is "[id]" or "[local path]")
            return SafeCaption(caption, text == "[id]" ? "Identifier" : "Local path");
        return text;
    }

    public static bool HasDetails(string? value) =>
        !string.Equals(value ?? string.Empty, Summary(value), StringComparison.Ordinal);

    public static string SafeCaption(string? caption, string fallback = "Details") =>
        string.IsNullOrWhiteSpace(caption) || GuidPattern().IsMatch(caption) || PathPattern().IsMatch(caption)
            ? fallback : caption;

    public static string[] ChoiceLabels(IEnumerable<string> values)
    {
        var labels = values.Select(value => Summary(value)).ToArray();
        var duplicates = labels.GroupBy(value => value, StringComparer.Ordinal)
            .Where(group => group.Count() > 1).Select(group => group.Key).ToHashSet(StringComparer.Ordinal);
        return labels.Select((label, index) => duplicates.Contains(label) ? $"{label} · option {index + 1}" : label).ToArray();
    }
}
