# Github orchestration (.yaml): Bicep

>[!NOTE]
> If you want to learn how to configure the AI Factory in `standalone mode` versus `Hub-connected centralized private DNS zones` with `BYOVnet`- [ setup starting page](../../../../../documentation/v2/20-29/24-end-2-end-setup.md)
>

## Note: 1-4 is needed only if you did not run the SCRIPTS as mentioned in [prerequisites](../../../../../documentation/v2/10-19/12-prerequisites-setup.md)

1) Run the start script [00-start.sh](../../../../../00-start.sh),  this will create some bootstrap-scripts at your repo root.
2) Run the file created at your root called: `01-aif-copy-aifactory-templates.sh`, this will create a folder at your root called `aifactory-templates` with templates for GHA workflows, and parameters.
3) Rename the newly created folder  `aifactory-templates` to  `aifactory` (protects you to overwrite your configuration if running the script again)
    - Note: Is is under the `aifactory` folder, you will configure your [base parameters](../../../../aifactory/parameters/) and other variables.
4) Run the file created at your root called: `02-GH-bootstrap-files.sh`, this will creat an .env file at your root.

## Continue with steps:5-8:

5) Edit the [base parameters](../../../../aifactory/parameters/). All files 12 files such as [10-esml-globals-1.json](../../../../aifactory/parameters/10-esml-globals-1.json)
6) Edit the [.env] variables at your root. (These will override some of the base parameters)
7) Run the file created at your root called: `03-GH-create-or-update-github-variables.sh`, that will copy values from .env to your Github repo as Environment variables, and secrets.
8) Run the Github action workflows

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