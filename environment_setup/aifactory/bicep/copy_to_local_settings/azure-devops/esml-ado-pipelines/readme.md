# Azure Devops orchestration (classic): Bicep

>[!NOTE]
> If you want to learn how to configure the AI Factory in `standalone mode` versus `Hub-connected centralized private DNS zones` with `BYOVnet`- [ setup starting page](../../../../../../documentation/v2/20-29/24-end-2-end-setup.md)
>

1) Import the json files as REALEASE pipelines in Azure Devops classic
2) Edit the Variables in the Azure Devops UI, the Variables tab.
3) Run first the [infra-aifactory-common.json](./infra-aifactory-common.json), to setup at least DEV common AIFactory environment
3) Run a project pipeline 
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