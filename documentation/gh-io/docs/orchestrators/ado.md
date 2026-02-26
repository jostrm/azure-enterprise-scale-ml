# Orchestrator — Azure DevOps

The AI Factory supports **Azure DevOps (ADO)** as a first-class orchestrator for all Bicep deployments.

---

## Configuration File

When using Azure DevOps, all parameters are defined in:

```
environment_setup/aifactory/bicep/copy_to_local_settings/
  azure-devops/esml-yaml-pipelines/variables/variables.yaml
```

Copy this file to your own repository and fill in all `<todo>` placeholders before running any pipeline.

---

## Service Connections

Six ADO service connections are required — two per environment:

| Variable | Purpose |
|---|---|
| `dev_service_connection` | Deploys resources to DEV subscription |
| `dev_seeding_kv_service_connection` | Reads secrets from DEV seeding Key Vault |
| `test_service_connection` | Deploys resources to STAGE subscription |
| `test_seeding_kv_service_connection` | Reads secrets from STAGE seeding Key Vault |
| `prod_service_connection` | Deploys resources to PROD subscription |
| `prod_seeding_kv_service_connection` | Reads secrets from PROD seeding Key Vault |

All service connections must be **Azure Resource Manager** type, authenticated via a Service Principal.

---

## Pipeline Structure

The ADO YAML pipelines are in:

```
environment_setup/aifactory/bicep/copy_to_local_settings/
  azure-devops/esml-yaml-pipelines/
```

### Triggering a deployment

1. Copy `variables.yaml` to your ADO repository.
2. Fill in all mandatory parameters (see [Standard Parameters](../parameters/standard.md)).
3. Run the pipeline — it will calculate networking, deploy all Bicep modules, and configure RBAC automatically.

---

## Bootstrap (First-time Setup)

Use the bootstrap scripts to set up your ADO environment:

```bash
bootstrap/02b-ADO-YAML-bootstrap-files.sh
```

For updates without overwriting existing variable values:

```bash
bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh
```
