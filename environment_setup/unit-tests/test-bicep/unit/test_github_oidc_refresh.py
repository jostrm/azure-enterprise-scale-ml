"""GitHub OIDC client assertions live five minutes; azure/login caches only the ARM token. A step that needs a token for
another audience (storage data plane) long after the job's login fails with AADSTS700024 (aif-138, 2026-10-30, step
102-project-lake-access 44 minutes after login), so the workflow logs in again right before it."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
PHASE = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml"


def _steps():
    workflow = yaml.safe_load(PHASE.read_text(encoding="utf-8"))
    return workflow["jobs"]["deploy-project"]["steps"]


def test_a_fresh_oidc_login_runs_right_before_the_lake_access_data_plane_step():
    steps = _steps()
    names = [step.get("name", "") for step in steps]
    lake = names.index("102-project-lake-access")
    refresh = [index for index, step in enumerate(steps[:lake])
               if step.get("uses", "").startswith("azure/login@") and "Refresh" in step.get("name", "")]
    assert refresh, "no OIDC refresh login before 102-project-lake-access"
    # Only other refresh logins sit between the refresh and the data-plane step.
    assert all(steps[i].get("uses", "").startswith("azure/login@") for i in range(refresh[0], lake))
    conditions = {steps[i]["if"] for i in refresh}
    assert any("inputs.json_identity_auth" in c and "!" not in c for c in conditions)
    assert any("!inputs.json_identity_auth" in c and "AZURE_CLIENT_ID != ''" in c for c in conditions)
    for i in refresh:
        assert steps[i]["with"]["client-id"] in ("${{ inputs.azure_client_id }}", "${{ env.AZURE_CLIENT_ID }}")
        assert "inputs.phase == 'infra'" in steps[i]["if"]
