using System.Globalization;
using System.Net;
using System.Numerics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using AsomRecordsAB.BaseLayer.VisualLearner;

CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
CultureInfo.CurrentUICulture = CultureInfo.InvariantCulture;

try
{
    if (args.Length != 4 || args[0] != "--report" || args[2] != "--output")
        throw new ArgumentException("Usage: VisualGuide --report <bicep-matrix.json> --output <docs-directory>");

    var bytes = File.ReadAllBytes(args[1]);
    using var reportDocument = JsonDocument.Parse(bytes);
    var report = reportDocument.RootElement;
    if (report.GetProperty("status").GetString() != "passed"
        || report.GetProperty("mode").GetString() != "offline-validation"
        || report.GetProperty("errors").GetArrayLength() != 0)
        throw new InvalidDataException("A passed, error-free offline-validation matrix report is required.");

    var counts = report.GetProperty("counts");
    var templates = report.GetProperty("templates").EnumerateArray().ToArray();
    var rows = templates.Select(template =>
    {
        if (template.GetProperty("status").GetString() != "passed")
            throw new InvalidDataException("Every template must have passed.");
        var file = RelativePath(template.GetProperty("file").GetString()!);
        var flags = template.GetProperty("flags").EnumerateArray().ToArray();
        var cases = template.GetProperty("cases").EnumerateArray().ToArray();
        var names = flags.Select(flag => flag.GetProperty("name").GetString()!).ToArray();
        if (names.Any(string.IsNullOrWhiteSpace) || names.Distinct(StringComparer.Ordinal).Count() != names.Length)
            throw new InvalidDataException("Flag names must be nonempty and unique within each entrypoint.");
        foreach (var binding in cases)
        {
            var values = binding.GetProperty("flags");
            if (values.EnumerateObject().Count() != flags.Length)
                throw new InvalidDataException("Each case must explicitly bind every flag.");
            foreach (var flag in flags)
            {
                var value = values.GetProperty(flag.GetProperty("name").GetString()!);
                var type = flag.GetProperty("type").GetString();
                if (!(type == "bool" && value.ValueKind is JsonValueKind.True or JsonValueKind.False)
                    && !(type == "string" && value.ValueKind == JsonValueKind.String
                        && value.GetString() is "true" or "false"))
                    throw new InvalidDataException("Flag bindings must preserve their bool/string type.");
            }
        }
        for (var a = 0; a < names.Length; a++)
        for (var b = a + 1; b < names.Length; b++)
        {
            var states = cases.Select(binding => PairState(binding, names[a], names[b])).Distinct().Count();
            if (states != 4)
                throw new InvalidDataException("Incomplete pair coverage: " + file);
        }
        var pairStates = checked(2 * flags.Length * (flags.Length - 1));
        if (pairStates != template.GetProperty("pair_states").GetInt32())
            throw new InvalidDataException("Pair-state total does not match actual case coverage.");
        return new TemplateRow(file, flags.Length, cases.Length, pairStates);
    }).ToArray();
    var sourceCount = report.GetProperty("reachable_source_templates").GetArrayLength();
    foreach (var path in report.GetProperty("reachable_source_templates").EnumerateArray())
        RelativePath(path.GetString()!);
    CheckCount("entrypoints", rows.Length);
    CheckCount("compiled_entrypoints", rows.Length);
    CheckCount("reachable_source_templates", sourceCount);
    CheckCount("flags", rows.Sum(row => row.Flags));
    CheckCount("cases", rows.Sum(row => row.Cases));
    CheckCount("bound_cases", rows.Sum(row => row.Cases));
    CheckCount("pair_states", rows.Sum(row => row.PairStates));
    void CheckCount(string name, int actual)
    {
        if (counts.GetProperty(name).GetInt32() != actual)
            throw new InvalidDataException("Inconsistent report count: " + name);
    }

    var phases = new[]
    {
        new PhaseInfo("push", "Push / PR", "Trigger the checks", "A local commit does not run remote CI. Push the commit to GitHub, open or update a pull request, or dispatch the workflow manually. GitHub checks all branches. ADO must first be registered from its YAML.", "01", "Repository event"),
        new PhaseInfo("config", "Configuration", "Follow the contracts", "The unit suite inventories 44 public ENABLE_* settings: 41 mapped contracts and three explicit exceptions. AMPLS and RETRIES have no GHA forwarding; AI_FACTORY_HUB records configuration intent only. These are not deployable-feature claims.", "02", "Inventory + wiring"),
        new PhaseInfo("unit", "Unit + syntax", "Check both operating systems", "Unit tests run on ubuntu-22.04 and windows-2022; syntax checks run on Linux. JUnit records actual tests, failures and platform skips. YAML duplicate keys, Python syntax and Bash -n are checked without executing deployment scripts.", "03", "Linux + Windows"),
        new PhaseInfo("bicep", "Bicep matrix", "Compile and bind inputs", "Install checksum-verified Bicep 0.44.1 and explicitly prepare declared public AVM dependencies. The validation step is then offline with --no-restore: compile real entrypoints and bind baseline, individual flips and all four states of every flag pair.", "04", "Compile + schema bind"),
        new PhaseInfo("review", "Review evidence", "Read the limits before merging", "Inspect JSON and JUnit artifacts, failures and skips. Pairwise input coverage does not evaluate ARM conditions or certify deployment. Configure GitHub required checks or Azure Repos Build validation separately; this change does neither automatically.", "05", "Artifacts + policies")
    };
    var yPositions = new double[] { 136, 108, 136, 108, 136 };
    var nodes = VisualLearnerPresentation.Normalize(phases.Select((phase, index) =>
        new VisualLearnerNode(phase.Id, phase.Label, "Schematic CI lane - not an Azure region",
            yPositions[index], 110 + index * 240, (VisualLearnerPhase)index,
            phase.Id == "config" || phase.Id == "review" ? VisualLearnerHealth.Attention : VisualLearnerHealth.Ready,
            phase.Detail)));
    var samples = Enumerable.Range(0, 128).Select(index =>
    {
        var elapsed = TimeSpan.FromSeconds(index * VisualLearnerMotion.CycleSeconds / 128);
        var flow = VisualLearnerMotion.FlowAt(nodes, elapsed)
            ?? throw new InvalidDataException("VisualLearner did not produce a flow.");
        return new FlowSample(elapsed.TotalSeconds, flow.From.Id, flow.To.Id, flow.Phase.ToString(),
            flow.Progress,
            flow.From.Longitude + (flow.To.Longitude - flow.From.Longitude) * flow.Progress,
            flow.From.Latitude + (flow.To.Latitude - flow.From.Latitude) * flow.Progress);
    }).ToArray();
    var staticFlow = VisualLearnerMotion.FlowAt(nodes, TimeSpan.FromSeconds(2.75))!;
    var demoTemplate = templates.OrderByDescending(template => template.GetProperty("flags").GetArrayLength()).First();
    var demoFlags = demoTemplate.GetProperty("flags").EnumerateArray()
        .Select(flag => flag.GetProperty("name").GetString()!)
        .OrderByDescending(name => name.StartsWith("enable", StringComparison.OrdinalIgnoreCase))
        .ThenBy(name => name, StringComparer.Ordinal).Take(2).ToArray();
    if (demoFlags.Length != 2)
        throw new InvalidDataException("The interactive pair demo requires an entrypoint with at least two flags.");
    var demoCases = demoTemplate.GetProperty("cases").EnumerateArray().ToArray();
    var pairExamples = Enumerable.Range(0, 4).Select(state =>
    {
        var matches = demoCases.Where(binding => PairState(binding, demoFlags[0], demoFlags[1]) == state).ToArray();
        return new PairExample(state, state / 2 == 1, state % 2 == 1,
            matches[0].GetProperty("name").GetString()!, matches.Length);
    }).ToArray();
    var demoFlagCount = demoTemplate.GetProperty("flags").GetArrayLength();
    var snapshot = new
    {
        status = "passed",
        mode = "offline-validation",
        reportFile = "bicep-matrix.json",
        reportSha256 = Convert.ToHexStringLower(SHA256.HashData(bytes)),
        bicepVersion = report.GetProperty("bicep_version").GetString(),
        counts = new
        {
            entrypoints = rows.Length,
            reachableSourceTemplates = sourceCount,
            flagOccurrences = rows.Sum(row => row.Flags),
            boundCases = rows.Sum(row => row.Cases),
            pairStates = rows.Sum(row => row.PairStates)
        },
        limits = report.GetProperty("limits").EnumerateArray().Select(limit => limit.GetString()).ToArray(),
        templates = rows
    };
    var scene = new
    {
        schemaVersion = 1,
        title = "PURPLE offline infrastructure CI",
        provenance = new
        {
            library = "AsomRecordsAB.VisualLearner",
            targetFramework = "net10.0",
            normalization = "VisualLearnerPresentation.Normalize",
            motion = "VisualLearnerMotion.FlowAt",
            coordinateSystem = "Schematic pixels only: Longitude -> x, Latitude -> y. NOT geographic; NOT Azure locations.",
            phaseMapping = phases.Select((phase, index) => new
            {
                libraryPhase = ((VisualLearnerPhase)index).ToString(),
                ciCaption = phase.Label
            }),
            explanation = "Portable scene and motion are real library outputs. Enum names are adapted to CI captions; no training, inference or agent execution is implied. Web/SVG rendering uses the cp theme, not the MAUI adapter."
        },
        snapshot,
        phases,
        nodes,
        cycleSeconds = VisualLearnerMotion.CycleSeconds,
        motionSamples = samples,
        staticFlow,
        pairDemo = new
        {
            file = RelativePath(demoTemplate.GetProperty("file").GetString()!),
            firstFlag = demoFlags[0],
            secondFlag = demoFlags[1],
            flagCount = demoFlagCount,
            generatedCases = demoCases.Length,
            fullAssignments = (BigInteger.One << demoFlagCount).ToString(CultureInfo.InvariantCulture),
            examples = pairExamples
        }
    };
    var jsonOptions = new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    jsonOptions.Converters.Add(new JsonStringEnumConverter());
    var sceneJson = JsonSerializer.Serialize(scene, jsonOptions);
    using var templateStream = Assembly.GetExecutingAssembly().GetManifestResourceStream("VisualGuide.guide.template.html")
        ?? throw new InvalidDataException("Missing embedded HTML template.");
    using var reader = new StreamReader(templateStream);
    var htmlTemplate = reader.ReadToEnd().Replace("\r\n", "\n");
    var theme = Regex.Match(htmlTemplate, @"/\* THEME START \*/([\s\S]+?)/\* THEME END \*/").Groups[1].Value;
    if (string.IsNullOrWhiteSpace(theme))
        throw new InvalidDataException("Missing shared theme.");
    var darkTheme = Regex.Match(theme, "html\\[data-theme=\"dark\"\\]\\s*\\{([^}]+)\\}").Groups[1].Value;
    var replacements = new Dictionary<string, string>
    {
        ["SVG"] = RenderSvg(true),
        ["SCENE_JSON"] = sceneJson,
        ["REPORT_HASH"] = H(snapshot.reportSha256),
        ["BICEP_VERSION"] = H(snapshot.bicepVersion ?? ""),
        ["METRICS"] = string.Join("\n", new[]
        {
            Metric(rows.Length, "pipeline entrypoints"),
            Metric(sourceCount, "reachable local sources"),
            Metric(rows.Sum(row => row.Flags), "bool/string flag occurrences"),
            Metric(rows.Sum(row => row.Cases), "schema-bound cases"),
            Metric(rows.Sum(row => row.PairStates), "covered pair states")
        }),
        ["PHASE_BUTTONS"] = string.Join("\n", phases.Select((phase, index) =>
            $"<button type=\"button\" class=\"phase-button\" data-phase=\"{H(phase.Id)}\" aria-pressed=\"{(index == 0 ? "true" : "false")}\"><span>{phase.Number}</span> {H(phase.Label)}</button>")),
        ["ROWS"] = string.Join("\n", rows.Select(row =>
            $"<tr><th scope=\"row\"><a href=\"../../../../{H(row.File)}\">{H(row.File)}</a></th><td>{row.Flags:N0}</td><td>{row.Cases:N0}</td><td>{row.PairStates:N0}</td></tr>")),
        ["LIMITS"] = string.Join("\n", snapshot.limits.Select(limit => $"<li>{H(limit ?? "")}</li>")),
        ["PAIR_FILE"] = H(RelativePath(demoTemplate.GetProperty("file").GetString()!)),
        ["FIRST_FLAG"] = H(demoFlags[0]),
        ["SECOND_FLAG"] = H(demoFlags[1]),
        ["PAIR_FLAG_COUNT"] = demoFlagCount.ToString(),
        ["PAIR_CASE_COUNT"] = demoCases.Length.ToString(),
        ["FULL_ASSIGNMENTS"] = (BigInteger.One << demoFlagCount).ToString(),
        ["PAIR_ROWS"] = string.Join("\n", pairExamples.Select(pair =>
            $"<tr data-pair=\"{pair.State}\"><th scope=\"row\">{pair.First.ToString().ToLowerInvariant()} / {pair.Second.ToString().ToLowerInvariant()}</th><td>{H(pair.CaseName)}</td><td>{pair.MatchingCases}</td></tr>"))
    };
    var html = Regex.Replace(htmlTemplate, @"\{\{([A-Z_]+)\}\}", match =>
        replacements.TryGetValue(match.Groups[1].Value, out var value)
            ? value : throw new InvalidDataException("Unknown template marker: " + match.Value));
    Directory.CreateDirectory(args[3]);
    Write("ci-visual-guide.html", html);
    Write("ci-flow.svg", RenderSvg(false));
    Write("ci-scene.json", sceneJson);
    Console.WriteLine($"Generated 3 deterministic artifacts from {rows.Length} entrypoints; all counts and pair states verified.");
    return 0;

    void Write(string name, string content) => File.WriteAllText(Path.Combine(args[3], name),
        content.TrimEnd() + "\n", new UTF8Encoding(false));

    string RenderSvg(bool interactive)
    {
        var svg = new StringBuilder();
        svg.AppendLine($"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1180 285\" role=\"{(interactive ? "group" : "img")}\" aria-labelledby=\"flow-title flow-description\">");
        svg.AppendLine("<title id=\"flow-title\">PURPLE offline CI learning flow</title>");
        svg.AppendLine("<desc id=\"flow-description\">Five schematic steps: Push or PR, Configuration, Unit and syntax, Bicep matrix, Review evidence. Non-geographic coordinates; no Azure locations. This is an explanatory sequence, not a scheduler: CI jobs run in parallel.</desc>");
        if (!interactive)
            svg.AppendLine($"<style>{theme}\n@media(prefers-color-scheme:dark){{:root{{{darkTheme}}}}}\n{SvgStyle()}</style>");
        svg.AppendLine("<rect class=\"flow-background\" x=\"0\" y=\"0\" width=\"1180\" height=\"285\" rx=\"16\"/>");
        svg.AppendLine("<text class=\"flow-caption\" x=\"24\" y=\"30\">SCHEMATIC CI FLOW - not geographic / not Azure locations</text>");
        svg.AppendLine("<defs><marker id=\"arrow\" markerWidth=\"8\" markerHeight=\"8\" refX=\"7\" refY=\"4\" orient=\"auto\"><path class=\"flow-arrow\" d=\"M0 0 L8 4 L0 8 Z\"/></marker></defs>");
        for (var index = 0; index < nodes.Count - 1; index++)
        {
            var from = nodes[index];
            var to = nodes[index + 1];
            var insetY = (to.Latitude - from.Latitude) * 100 / (to.Longitude - from.Longitude);
            svg.AppendLine($"<path class=\"flow-edge\" d=\"M {from.Longitude + 100} {from.Latitude + insetY} L {to.Longitude - 100} {to.Latitude - insetY}\" marker-end=\"url(#arrow)\"/>");
        }
        foreach (var node in nodes)
        {
            var phase = phases.Single(phase => phase.Id == node.Id);
            var accessible = interactive
                ? $" role=\"button\" tabindex=\"0\" data-node=\"{H(node.Id)}\" aria-label=\"{H(phase.Label)}: {H(phase.Title)}\" aria-pressed=\"{(node.Id == "push" ? "true" : "false")}\""
                : "";
            svg.AppendLine($"<g class=\"flow-node\"{accessible}>");
            svg.AppendLine($"<title>{H(node.Detail)}</title>");
            svg.AppendLine($"<rect class=\"node-box\" x=\"{node.Longitude - 100}\" y=\"{node.Latitude - 40}\" width=\"200\" height=\"80\" rx=\"10\"/>");
            svg.AppendLine($"<text class=\"node-number\" x=\"{node.Longitude - 82}\" y=\"{node.Latitude - 16}\">{phase.Number}</text>");
            svg.AppendLine($"<text class=\"node-title\" x=\"{node.Longitude}\" y=\"{node.Latitude + 9}\" text-anchor=\"middle\">{H(node.Name)}</text>");
            svg.AppendLine($"<text class=\"node-note\" x=\"{node.Longitude}\" y=\"{node.Latitude + 66}\" text-anchor=\"middle\">{H(phase.ShortDetail)}</text>");
            if (node.Health == VisualLearnerHealth.Attention)
                svg.AppendLine($"<text class=\"node-attention\" x=\"{node.Longitude + 75}\" y=\"{node.Latitude - 14}\" aria-label=\"Attention: read the caveats\">!</text>");
            svg.AppendLine("</g>");
        }
        var x = staticFlow.From.Longitude + (staticFlow.To.Longitude - staticFlow.From.Longitude) * staticFlow.Progress;
        var y = staticFlow.From.Latitude + (staticFlow.To.Latitude - staticFlow.From.Latitude) * staticFlow.Progress;
        svg.AppendLine($"<circle id=\"flow-marker\" class=\"flow-marker\" cx=\"{x}\" cy=\"{y}\" r=\"7\" aria-hidden=\"true\"/>");
        svg.AppendLine("<text class=\"flow-caption\" x=\"24\" y=\"245\">Legend: numbered box = teaching step; ! = caveat; moving dot = illustrative library motion, not live CI progress.</text>");
        svg.AppendLine("<text class=\"flow-caption\" x=\"24\" y=\"267\">Unit Linux + Windows, syntax Linux, Bicep Linux are parallel CI jobs. Preparing tools/modules may use the network.</text>");
        svg.AppendLine("</svg>");
        return svg.ToString().Replace("\r\n", "\n");
    }
}
catch (Exception error) when (error is ArgumentException or IOException or JsonException or KeyNotFoundException or InvalidOperationException or OverflowException)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

static string H(string value) => WebUtility.HtmlEncode(value);
static string Metric(int value, string caption) =>
    $"<div class=\"metric\"><strong>{value:N0}</strong><span>{H(caption)}</span></div>";
static string RelativePath(string value)
{
    if (string.IsNullOrWhiteSpace(value) || value.Contains('\\') || value.Contains(':')
        || value.StartsWith('/') || value.Split('/').Any(part => part is "." or ".." or ""))
        throw new InvalidDataException("Report template paths must be repository-relative.");
    return value;
}
static bool FlagValue(JsonElement value) => value.ValueKind switch
{
    JsonValueKind.True => true,
    JsonValueKind.False => false,
    JsonValueKind.String when value.GetString() == "true" => true,
    JsonValueKind.String when value.GetString() == "false" => false,
    _ => throw new InvalidDataException("Expected a boolean or canonical true/false string.")
};
static int PairState(JsonElement binding, string first, string second)
{
    var flags = binding.GetProperty("flags");
    return (FlagValue(flags.GetProperty(first)) ? 2 : 0) + (FlagValue(flags.GetProperty(second)) ? 1 : 0);
}
static string SvgStyle() => """
.flow-background { fill:var(--cp-surface); }
.flow-caption,.node-note { fill:var(--cp-text-muted); font:13px "Segoe UI",Aptos,Calibri,sans-serif; }
.flow-edge { stroke:var(--cp-border-strong); stroke-width:2; fill:none; }
.flow-arrow { fill:var(--cp-border-strong); }
.node-box { fill:var(--cp-surface-soft); stroke:var(--cp-border-strong); stroke-width:1.5; }
.node-number { fill:var(--cp-accent); font:600 14px "Segoe UI",Aptos,Calibri,sans-serif; }
.node-title { fill:var(--cp-text); font:600 18px "Segoe UI",Aptos,Calibri,sans-serif; }
.node-attention { fill:var(--cp-accent); font:700 18px "Segoe UI",Aptos,Calibri,sans-serif; }
.flow-marker { fill:var(--cp-accent); stroke:var(--cp-surface); stroke-width:2; }
""";

internal sealed record TemplateRow(string File, int Flags, int Cases, int PairStates);
internal sealed record PhaseInfo(string Id, string Label, string Title, string Detail, string Number, string ShortDetail);
internal sealed record FlowSample(double Seconds, string From, string To, string LibraryPhase, double Progress, double X, double Y);
internal sealed record PairExample(int State, bool First, bool Second, string CaseName, int MatchingCases);
