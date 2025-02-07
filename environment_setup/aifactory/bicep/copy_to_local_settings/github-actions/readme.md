# Github orchestration (.yaml): Bicep

>[!NOTE]
> If you want to learn how to configure the AI Factory in `standalone mode` versus `Hub-connected centralized private DNS zones` with `BYOVnet`- [ setup starting page](../../../../../documentation/v2/20-29/24-end-2-end-setup.md)
>

1) Run the start script [00-start.sh](../../../../../00-start.sh),  this will create some scripts at your repo root.
2) Run the file created at your root called: `01-aif-copy-aifactory-templates.sh`, this will create a folder at your root called `aifactory-templates` with templates for GHA workflows, and parameters.
3) Run the file created at your root called: `02a-GH-bootstrap-files.sh`, this will creat an .env file at your root. It will also create another file called `03a-GH-create-or-update-github-variables.sh`
4) Edit the [.env] variables
5) Run the file created at your root called: `03a-GH-create-or-update-github-variables.sh`, that will copy values from .env to your Github repo as Environment variables, and secrets. 
6) Run the Github action workflows

## Workflow: AIFactory Common 
Start with setting up a common AIFactory environment, example, the DEV environment
- [infra-aifactory-common.yaml](./esml-infra-common/infra-aifactory-common.yaml)

## Workflow: AIFactory projects
Then you can import and run the pipelines to setup 1-M projects. There are 2 AIFactory project types supported as of now: 
- [infra-project-genai.yaml](./infra-project-genai.yml)
- [infra-project-esml.yaml](./infra-project-esml.yml)


> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>