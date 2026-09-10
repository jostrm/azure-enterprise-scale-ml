using System.Text.Json.Nodes;

namespace ESAIF.ConfigWizard.Services;

public sealed record WizardIdentity(string Folder, string ProjectNumber, string ScaleSetId)
{
    public bool HasProject => ProjectNumber.Length > 0;
    public bool HasScaleSet => ScaleSetId.Length > 0;
    public string ProjectLabel => HasProject ? $"Project {ProjectNumber} · selected" : "No project selected";
    public string ScaleSetLabel => HasScaleSet ? $"Scale set {ScaleSetId} · selected" : "No scale set selected";

    public static WizardIdentity FromState(JsonObject state, string folder)
    {
        static string Read(JsonObject state, string key)
        {
            var value = state[key]?.ToString().Trim() ?? string.Empty;
            return value.Contains("<todo>", StringComparison.OrdinalIgnoreCase) ? string.Empty : value;
        }

        // Python persists scale sets by the normalized suffix, not the full factory name.
        var scaleSet = Read(state, "admin_aifactorySuffixRG").TrimStart('-').Trim();
        return new WizardIdentity(
            folder.Trim(),
            Read(state, "project_number_000"),
            scaleSet);
    }

    public bool IsProjectSelected(string folder, string projectNumber) =>
        SameFolder(folder) && HasProject &&
        ProjectNumber.Equals(projectNumber.Trim(), StringComparison.OrdinalIgnoreCase);

    public bool IsScaleSetSelected(string folder, string scaleSetId) =>
        SameFolder(folder) && HasScaleSet &&
        ScaleSetId.Equals(scaleSetId.Trim(), StringComparison.OrdinalIgnoreCase);

    private bool SameFolder(string folder) =>
        FactoryNetworkSession.SameFolder(Folder, folder);
}
