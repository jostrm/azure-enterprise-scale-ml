# Orchestrator — GitHub Actions

The AI Factory supports **GitHub Actions (GHA)** as a first-class orchestrator for all Bicep deployments, equivalent in functionality to the Azure DevOps option.

---

## Configuration File

When using GitHub Actions, all parameters are defined in:

```
environment_setup/aifactory/bicep/copy_to_local_settings/
  github-actions/.env.template
```

Copy this file to your own repository as `.env` (or use GitHub Actions environment secrets/variables) and fill in all `<todo>` placeholders.

---

## Authentication

GitHub Actions uses **federated credentials** (OIDC) or Service Principal credentials stored as GitHub secrets:

| Secret | Description |
|---|---|
| `AZURE_CLIENT_ID` | Service principal App ID |
| `AZURE_CLIENT_SECRET` | Service principal secret (from seeding KV) |
| `AZURE_TENANT_ID` | Azure tenant ID |
| `AZURE_SUBSCRIPTION_ID_DEV` | DEV subscription ID |
| `AZURE_SUBSCRIPTION_ID_TEST` | STAGE subscription ID |
| `AZURE_SUBSCRIPTION_ID_PROD` | PROD subscription ID |

---

## Workflow Structure

GitHub Actions workflows are in:

```
.github/workflows/
```

### Triggering a deployment

1. Copy `.env.template` to your GHA repository and configure all mandatory parameters.
2. Add required secrets to your GitHub repository or environment.
3. Trigger the workflow manually (`workflow_dispatch`) or via a push to the designated branch.

---

## Bootstrap (First-time Setup)

Use the bootstrap scripts to set up your GitHub Actions environment:

```bash
bootstrap/02a-GH-bootstrap-files.sh
```

For updates without overwriting existing variable values:

```bash
bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh
```

---

## This Documentation Site

This MkDocs documentation site is itself deployed via GitHub Actions. See the workflow at `.github/workflows/deploy-docs.yml`.
