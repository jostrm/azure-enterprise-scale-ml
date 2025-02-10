# Azure Devops orchestration (classic): Bicep

## Note: 1-3 is needed only if you did not run the SCRIPTS as mentioned in [prerequisites](../../../../../documentation/v2/10-19/12-prerequisites-setup.md)

>[!IMPORTANT]
> If this link works: [base parameters](../../../../aifactory/parameters/) you should not do thes steps 1-3 (you already have copied templates files locally)
>

1) Run the start script [00-start.sh](../../../../../00-start.sh),  this will create some bootstrap-scripts at your repo root.
2) Run the file created at your root called: `01-aif-copy-aifactory-templates.sh`, this will create a folder at your root called `aifactory-templates` with templates for GHA workflows, and parameters.
3) Rename the newly created folder  `aifactory-templates` to  `aifactory` (protects you to overwrite your configuration if running the script again)
    - Note: Is is under the `aifactory` folder, you will configure your [base parameters](../../../../aifactory/parameters/) and other variables.

## Steps:4-7:

>[!NOTE]
> If you want to learn how to configure the AI Factory in `standalone mode` versus `Hub-connected centralized private DNS zones` with `BYOVnet`- [ setup starting page](../../../../../../documentation/v2/20-29/24-end-2-end-setup.md)
>

4) Import the json files as RELEASE pipelines in Azure Devops classic
5) Edit the Variables in the Azure Devops UI, the Variables tab.
6) Run first the [infra-aifactory-common.json](./infra-aifactory-common.json), to setup at least DEV common AIFactory environment
7) Run a project pipeline 
    - ESML project: [infra-project-esml.json](./infra-project-esml.json)
    - GenAI project: [infra-project-genai.json](./infra-project-genai.json)

If you want to onboard more people to an existing AIFActory project.
- Import also [add-project-member.json](./add-project-member.json)
- Edit variables & Run

If you want to onboard more people as AIFActory core team, to have access to the COMMON area
- Import also [add-coreteam-member.json](./add-coreteam-member.json)
- Edit variables & Run

> [!TIP]
>  Do you want to use Github instead of Azure Devops? Then you can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage).
>

## Very detailed instructions - screenshots

[Setup AIFactory - Infra Automation (AzureDevops classic + BICEP)](../../../../../../documentation/v2/10-19/13-setup-aifactory.md)