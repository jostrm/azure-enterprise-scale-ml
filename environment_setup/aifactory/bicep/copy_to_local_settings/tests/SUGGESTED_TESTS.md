# Suggested additional tests

Beyond the requested scenarios (common deploy, project all-enabled/all-disabled,
network modes, BYO modes, env/var parity, PaaS reachability):

## IaC validation (offline, cheap)
- bicep build / `az bicep build` on every esml-genai-1/esml-common template — no errors.
- bicep lint clean (bicepconfig.json rules).
- `az deployment group what-if` per scenario (no real deploy) to detect drift.
- bicepparam files parse and reference existing params (no orphans).

## Config integrity
- No `<todo>` defaults leak into committed variables.yaml.
- Mandatory vars present; mutually exclusive flags rejected (e.g. CMK + soft-delete<7).
- disableLocalAuth=true ⇒ key-based auth actually disabled on accounts.

## Security / governance
- Private mode: 0 public endpoints; NSGs deny public; key auth disabled.
- RBAC: managed identity has only expected roles (least privilege).
- Defender-for-AI flags propagate to deployed resources.

## Connectivity matrix
- Foundry ⇄ Search, Storage, ACR, KeyVault, Cosmos all private-resolvable.
- AKS/ACA egress respects outbound type; project subnet isolation.
- nslookup returns RFC1918 for every private endpoint.

## Lifecycle / cost
- Re-deploy idempotency (deploy twice = no diff).
- ENABLE_DELETE_FOR_DISABLED_RESOURCES removes disabled services.
- Teardown leaves zero orphaned role assignments / DNS records.
- Cost guard: scenario stays under a budget ceiling (az consumption).
