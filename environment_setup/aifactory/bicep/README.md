# BICEP to provision the AIFactory and new projects
This repo is BICEP first. Meaning that Terraform has lower prio. 

You can use either **GITHUB** or **Azure Devops** automation pipelines (that uses BICEP under neath the hood)

You do **not need** to interact with either BICEP or Terraform, since the AIFactory provides automation pipelines.

We recommend to use the GITHUB option, that uses Github actions with workflows, and also is provided as a TEMPLATE Github repository.

The Azure Devops option, provides automation pipelines (option of choosing classic release pipeline, or the new way - YAML build pipeline)

## Alternative: Github Actions
Start with setting up a common AIFactory environment, example, the DEV environment
- [Github Action - readme.md](./copy_to_local_settings/github-actions/readme.md)

## Alternative: Azure Devops
- [Azure Devops - readme.md](./copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md)

> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>