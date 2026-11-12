---
hide:
  - navigation
  - toc
---

# Architecture

An AI Factory has a common part and one resource group for each project. Every project starts from the same
template, and the team switches on the Azure services it needs. You choose one of three
[hub modes](reference/hub-and-network-modes.md) when you create the Factory.

Each image shows the Factory with one hub mode, and how it connects to Microsoft 365, Microsoft Power
Platform, SharePoint, Microsoft Fabric and the AI gateway. A numbered blue circle is a code template for that
part: select the circle, or find the number in [the table](#the-numbers-on-the-images) below.

=== "External hub"

    The Factory connects to a hub that you already own, with VNet peering. Your hub gives the VPN or
    ExpressRoute connection, the firewall and the private DNS zones. Choose it when you have a landing zone,
    or when several Factories share one hub.

    <div class="esaf-architecture">
      <object type="image/svg+xml" data="../assets/architecture/esaf-architecture-external-hub.svg" aria-label="Diagram that shows the AI Factory connected to an external hub, with Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway.">
        <img src="../assets/architecture/esaf-architecture-external-hub.png" alt="Diagram that shows the AI Factory connected to an external hub, with Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway." width="1600" height="1010">
      </object>
    </div>

    [Open the image at full size](assets/architecture/esaf-architecture-external-hub.svg) |
    [PNG](assets/architecture/esaf-architecture-external-hub.png)

=== "Own hub"

    The Factory creates its own hub in its Dev network, with a VPN gateway, a DNS Private Resolver and
    Bastion. Choose it when you need private access and have no central hub.

    <div class="esaf-architecture">
      <object type="image/svg+xml" data="../assets/architecture/esaf-architecture-own-hub.svg" aria-label="Diagram that shows the AI Factory with its own hub, with Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway.">
        <img src="../assets/architecture/esaf-architecture-own-hub.png" alt="Diagram that shows the AI Factory with its own hub, with Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway." width="1600" height="1010">
      </object>
    </div>

    [Open the image at full size](assets/architecture/esaf-architecture-own-hub.svg) |
    [PNG](assets/architecture/esaf-architecture-own-hub.png)

=== "Standalone"

    The Factory has no hub. It keeps its network and its private DNS zones in the common resource group, and
    people reach the services over the internet from the IP addresses you allow. Choose it to evaluate ESAF
    or to run a workshop. Networking is hybrid or public.

    <div class="esaf-architecture">
      <object type="image/svg+xml" data="../assets/architecture/esaf-architecture-standalone.svg" aria-label="Diagram that shows a standalone AI Factory without a hub, with Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway.">
        <img src="../assets/architecture/esaf-architecture-standalone.png" alt="Diagram that shows a standalone AI Factory without a hub, with Microsoft 365, Power Platform, SharePoint, Fabric and the AI gateway." width="1600" height="1010">
      </object>
    </div>

    [Open the image at full size](assets/architecture/esaf-architecture-standalone.svg) |
    [PNG](assets/architecture/esaf-architecture-standalone.png)

## The numbers on the images

The numbers mean the same on all three images. Each row links to the template in the
[code templates library](code-templates/index.md) and to its folder.

<!-- code-templates:numbers -->

## How each connection works

| Connection | How it works | Settings and templates |
| --- | --- | --- |
| **Microsoft 365**: Teams and Microsoft 365 Copilot | You publish an agent of the Foundry project. Azure Bot Service passes each message from Teams or Copilot to that agent. | `enableBotService`, `botFoundryAgentName`, `botFoundryProjectResourceId`. Template 1. |
| **Microsoft Power Platform**: Copilot Studio and Power Automate | The common virtual network has a subnet that is delegated to Power Platform (`common_pbi_subnet_name`). You connect your Power Platform environment to that subnet. Agents and flows then call the Factory over the private network. | `common_pbi_subnet_name`, `common_pbi_subnet_cidr`. No code template yet. |
| **SharePoint** | SharePoint is a knowledge source outside the Factory. Foundry IQ connects to it, and your agents answer from it. | Template 5 keeps each reader's permissions and has an optional SharePoint sync. |
| **AI gateway**: API Management, or Kong | One endpoint in front of a pool of model deployments, with retries when a backend is throttled. Kong is the alternative when your organization runs Kong. The gateway has its own pipeline. | `ENABLE_APIM` or `ENABLE_KONG`, and the `apimGateway...` and `kongGateway...` settings. Template 7. See [AI gateways](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/documentation/v2/20-29/29-factory-AI-Gateways.md). |
| **Microsoft Fabric** | A Fabric data agent answers questions about your Fabric data. A Foundry agent calls it as a tool. | Templates 3, 4 and 18. |
| **Azure Machine Learning** | A Foundry agent trains, retrains and scores models in the workspace of the project. | `enableAzureMachineLearning`. Templates 8 and 14. |

Every setting is explained in [Every variable in variables.json](parameters/variables.md), and the
[Azure resource library](resources/index.md) lists the services by category.

## Watch the hub options

The configuration wizard has an animation for each hub mode. The tabs follow your choice above. If your
device asks for reduced motion, you get a still image.

=== "External hub"

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../assets/animations/factory-topology-external-hub.png">
      <img src="../assets/animations/factory-topology-external-hub.gif" alt="An AI Factory connects to a separately owned external enterprise hub." width="1400" height="943" loading="lazy">
    </picture>

    [Animated SVG](assets/animations/factory-topology-external-hub.svg) |
    [GIF](assets/animations/factory-topology-external-hub.gif) |
    [Still image](assets/animations/factory-topology-external-hub.png)

=== "Own hub"

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../assets/animations/factory-topology-own-hub.png">
      <img src="../assets/animations/factory-topology-own-hub.gif" alt="A standalone AI Factory includes its own hub and connected project networks." width="1400" height="919" loading="lazy">
    </picture>

    [Animated SVG](assets/animations/factory-topology-own-hub.svg) |
    [GIF](assets/animations/factory-topology-own-hub.gif) |
    [Still image](assets/animations/factory-topology-own-hub.png)

=== "Standalone"

    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcset="../assets/animations/factory-topology-standalone.png">
      <img src="../assets/animations/factory-topology-standalone.gif" alt="A standalone AI Factory operates without a hub connection." width="1400" height="889" loading="lazy">
    </picture>

    [Animated SVG](assets/animations/factory-topology-standalone.svg) |
    [GIF](assets/animations/factory-topology-standalone.gif) |
    [Still image](assets/animations/factory-topology-standalone.png)

## Continue

- [Choose a hub mode and a networking mode](reference/hub-and-network-modes.md)
- [Create your AI Factory](setup/02-create-factory.md)
- [Code templates library](code-templates/index.md)
- [Agent Factory](concepts/templates/genaiops.md), [Model Factory](concepts/templates/mlops.md) and
  [DataOps](concepts/templates/dataops.md)
