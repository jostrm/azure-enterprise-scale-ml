[Docs](../README.md) › [Usage docs](README.md)

# Usage prerequisites

Every page in the Usage docs assumes the three things below. Check them once.

## An ESAF project

You need an **ESAF project**: your team's own resource group in an AI Factory, for example `project001` in
Dev. You get one in either of two ways.

**Your platform team set up a Factory.** Ask them for your project number and environment. If there is no
Factory yet, see [Setup docs - platform team](../quickstarts/README.md).

**Or try it quickly.** Select **Deploy to Azure** to deploy a test Factory with project 001 (preview):

[![Deploy to Azure button that opens the ESAF quick-test template in the Azure portal.](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fjostrm%2Fazure-enterprise-scale-ml%2Fportal-125%2Fportal%2Fazuredeploy.json/uiFormDefinitionUri/https%3A%2F%2Fraw.githubusercontent.com%2Fjostrm%2Fazure-enterprise-scale-ml%2Fportal-125%2Fportal%2Fform.json)

> [!NOTE]
> Deploy to Azure is meant for a quick test, not for a governed Factory. See
> [what it deploys and what it leaves out](../20-29/24-end-2-end-setup.md#try-it-first-with-deploy-to-azure-preview).

## Access to your project

- **Membership of your project's Microsoft Entra group.** Your platform team adds you. See
  [personas](../20-29/25-personas.md) for the roles.
- **A way into the private network**, when your project uses private networking: the VPN, Bastion or a
  machine inside the network. See [get access to the AI Factory](../30-39/31-jumphost-vm-bastion-access.md).

## Tools on your machine

| Tool | Version | Used for |
|---|---|---|
| [Python](https://www.python.org/downloads/) | 3.13 for agents; 3.10 to 3.13 for ML | Running the templates |
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) | Current | Signing in: `az login --tenant <your tenant ID>` |
| [Git](https://git-scm.com/downloads) | Current | Getting the templates in `usecase_code` |
| PowerShell | 7 or later | Running the commands as written |

**Back:** [Usage docs](README.md)

**Next:** [Quickstart: Run your first agent in your ESAF project](01-first-agent.md)
