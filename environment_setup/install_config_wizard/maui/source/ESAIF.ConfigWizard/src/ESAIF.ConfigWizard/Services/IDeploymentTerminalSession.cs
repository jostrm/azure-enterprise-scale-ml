using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public interface IDeploymentTerminalSession
{
    Task OpenAsync(string folder, ProjectDeploymentDraft draft);
}
