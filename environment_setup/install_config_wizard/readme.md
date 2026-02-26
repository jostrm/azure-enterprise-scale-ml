# AI Factory Configuration Wizard

The **AI Factory Configuration Wizard** is a guided, form-based desktop tool that simplifies the initial setup of an Enterprise Scale AI Factory. Instead of manually editing configuration files, the wizard walks you through every required parameter, validates your inputs in real time, and generates a correctly populated `.env.template` (GitHub Actions) or `variables.yaml` (Azure DevOps) file — ready to be used directly in your CI/CD pipeline.

![AI Factory Configuration Wizard](images/aifactory-config-wizard-01.png)

## Why use the Wizard?

- **Reduces misconfiguration risk** — mandatory fields are marked and validated before the file is generated
- **Speeds up first-time setup** — no need to read through a large configuration file to find what to change
- **ITSM-friendly** — core teams can generate the correct configuration directly from a service ticket and trigger the pipeline on behalf of the requesting team. Or get the "initial full configuration", where the ITSM tickets only contain the *project specifics* such as *which resources a team wants to order* e.g. have enabled=true (checkboxes in Wizard)

## Download

| Platform | File |
|---|---|
| Windows | [aifactory-config-windows.zip](aifactory-config-windows.zip) |
| Linux | [aifactory-config-linux.gzip](aifactory-config-linux.gzip) |
| macOS | [aifactory-config-macos.tar](aifactory-config-linux.tar) |

## Documentation

Full parameter reference: [https://jostrm.github.io/azure-enterprise-scale-ml/parameters/](https://jostrm.github.io/azure-enterprise-scale-ml/parameters/)
