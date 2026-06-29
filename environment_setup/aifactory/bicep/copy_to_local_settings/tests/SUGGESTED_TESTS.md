# Suggested additional tests

Beyond the requested scenarios (common deploy, project all-enabled/all-disabled,
network modes, BYO modes, env/var parity, PaaS reachability):

## IaC validation (offline, cheap)
- [x] bicep build / `az bicep build` on every esml-genai-1/esml-common template — no errors. (domain/iac.py + unit/test_iac_build_mock.py, integration/test_iac_build.py)
- [x] bicep lint clean (bicepconfig.json rules). (iac.lint_clean)
- bicepparam files parse and reference existing params (no orphans). (iac.bicepparam_parses)
- `az deployment group what-if` per scenario (no real deploy) to detect drift. [x] (iac.what_if_clean)

## Config integrity
- [x] No `<todo>` defaults leak into committed mandatory env defaults. (governance.placeholder_leaks)
- [x] Mandatory vars present; mutually exclusive flags rejected (CMK + soft-delete<7). (governance.missing_mandatory / cmk_softdelete_conflict)
- [x] disableLocalAuth=true ⇒ key-based auth actually disabled. (governance.key_auth_disabled)

## Security / governance
- [x] Private mode: 0 public endpoints. (governance.public_endpoint_count)
- RBAC: managed identity has only expected roles (least privilege). [x] (governance.identity_roles)
- Defender-for-AI flags propagate to deployed resources.

## Connectivity matrix
- [x] Foundry ⇄ Search, Storage reachable (paas.foundry_can_reach_search/storage).
- AKS/ACA egress respects outbound type; project subnet isolation.
- nslookup returns RFC1918 for every private endpoint.

## Lifecycle / cost
- Re-deploy idempotency (deploy twice = no diff).
- [x] Idempotent teardown of project/common RG (factory.cleanup_common, project.cleanup_project).
- ENABLE_DELETE_FOR_DISABLED_RESOURCES removes disabled services.
- Teardown leaves zero orphaned role assignments / DNS records.
- Cost guard: scenario stays under a budget ceiling (az consumption).
