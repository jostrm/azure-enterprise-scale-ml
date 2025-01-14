# Azure Devops orchestration (.yaml): Bicep
Edit the [Variables](./variables/variables.yaml) file, and import Build pipeline in Azure Devops

The build pipelines you will import, is the yaml files below.

## Pipeline: AIFactory Common 
Start with setting up a common AIFactory environment, example, the DEV environment
- [infra-aifactory-common.yaml](./esml-infra-common/infra-aifactory-common.yaml)

## Pipelines: AIFactory projects
Then you can import and run the pipelines to setup 1-M projects. There are 2 AIFactory project types supported as of now: 
- [infra-project-genai.yaml](./esml-infra-project/infra-project-genai.yaml)
- [infra-project-esml.yaml](./esml-infra-project/infra-project-esml.yaml)


> [!TIP]
>  Do you want to use Github instead of Azure Devops? Then you can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage).
>