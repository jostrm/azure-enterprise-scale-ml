---
id: deploy-to-azure-portal
status: proposed
sources:
  - bootstrap/lib/aifactory_scaleset_config.py
  - bootstrap/lib/create-new-aifactory-scaleset.sh
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml
  - environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py
  - environment_setup/aifactory/bicep/scripts/search-region-fallback.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_simple_bootstrap.py
graph_symbols:
  - bootstrap/lib/aifactory_scaleset_config.py::function:simple_mode_values
  - bootstrap/lib/aifactory_scaleset_config.py::function:apply_gha
reviewed_source: 'release/v1.24 dfad2e45; observed 2026-10-25'
---
# Deploy to Azure portal button (proposal)

Status: **proposed**. Draft written while the portal-124 work is in progress; it is completed in the same branch.
