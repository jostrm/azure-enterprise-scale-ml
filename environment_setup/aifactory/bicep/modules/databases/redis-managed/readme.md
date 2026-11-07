# Azure Managed Redis

`enableRedisManaged` deploys **Azure Managed Redis**, not the retiring Azure
Cache for Redis Enterprise E/F tiers. It is independent of `enableRedisCache`,
which retains the existing `modules/databases/redis` implementation.

## Configuration and pipeline

Merge these exact keys into the `dev` object of
`environment_setup/aifactory/variables.json` (retain your other settings):

```json
{
  "dev": {
    "enableRedisManaged": true,
    "enableRedisCache": false,
    "skuRedisManagedDev": "Balanced_B1",
    "skuRedisManagedStageProd": "Balanced_B5",
    "highAvailabilityRedisManaged": "Enabled",
    "evictionPolicyRedisManaged": "NoEviction",
    "clusteringPolicyRedisManaged": "OSSCluster"
  }
}
```

Only `enableRedisManaged: true` is required; the other Managed Redis values above
are the defaults. The switch defaults to **false** when absent. JSON booleans and
the existing `"true"` / `"false"` string convention are accepted; other values fail.
`dev` is the shared baseline; `stage_prod` overrides it for Stage/Prod, and an
exact `test` or `prod` section overrides that. Stage maps to Bicep `test`.

Use the normal JSON-configured project infrastructure pipeline. Both GitHub
Actions and Azure DevOps apply JSON overrides before validation and pass all six
settings to `64-databases` (`esml-genai-1/04-databases.bicep`). A Managed-only
selection does not depend on any legacy Redis or other database enable switch.
Normal foundation/core phases must run first for the project identity, network
and shared monitoring prerequisites. The ADO `debug_disable_64_databases`
diagnostic skip still applies; leave it false. Project teardown skips provisioning.

For copied configurations, refresh the provider templates as well as Bicep.
ADO `variables.yaml` exposes the same camelCase keys. GitHub `.env.template`,
variable registration and workflow bindings expose:

| JSON / ADO | GitHub variable | Default |
|---|---|---|
| `enableRedisManaged` | `ENABLE_REDIS_MANAGED` | `false` |
| `skuRedisManagedDev` | `SKU_REDIS_MANAGED_DEV` | `Balanced_B1` |
| `skuRedisManagedStageProd` | `SKU_REDIS_MANAGED_STAGEPROD` | `Balanced_B5` |
| `highAvailabilityRedisManaged` | `HIGH_AVAILABILITY_REDIS_MANAGED` | `Enabled` |
| `evictionPolicyRedisManaged` | `EVICTION_POLICY_REDIS_MANAGED` | `NoEviction` |
| `clusteringPolicyRedisManaged` | `CLUSTERING_POLICY_REDIS_MANAGED` | `OSSCluster` |

Bootstrap Simple Mode also offers the opt-in `redis-managed` resource and includes
`Microsoft.Cache` in its required provider list when selected.

## Resource and configuration contract

- Cluster: `Microsoft.Cache/redisEnterprise@2025-07-01`, plus its required `default`
  database and data-access policy assignments using the same API.
- This accelerator supports the bounded SKU subset `Balanced_B0`, `Balanced_B1`,
  `Balanced_B5`, `Balanced_B10` for either environment. **No `sku.capacity`**:
  capacity is only for the older Enterprise/EnterpriseFlash SKUs.
- HA accepts `Enabled` or `Disabled`. Keep HA enabled for production. Azure does
  not support changing an existing HA instance from Enabled to Disabled.
- Eviction accepts `AllKeysLFU`, `AllKeysLRU`, `AllKeysRandom`, `NoEviction`,
  `VolatileLFU`, `VolatileLRU`, `VolatileRandom`, `VolatileTTL`.
  `NoEviction` rejects writes when memory fills rather than evicting cached data.
- Clustering accepts `OSSCluster`, `EnterpriseCluster`, `NoCluster`. NoCluster is
  limited to 25 GB; all supported SKUs above fit that limit. Changing an existing
  OSS/Enterprise clustering policy requires a separate migration/recreation plan.
- Persistence and geo-replication are not configured. This is a cache, not a
  durable system of record. Encryption at rest uses Microsoft-managed keys.
  This module does not implement the broader factory CMK option.
- Invalid active settings fail before deployment, even if preflight is skipped.
  Inactive settings and the unused environment's SKU are not rewritten.
  Region availability, quota, scaling restrictions and actual capacity remain
  Azure constraints; there is no SKU/region retry or delete/recreate fallback.
- Only commercial `AzureCloud` is supported here. The runtime guard and Bicep
  reject enabled deployments in other clouds rather than guessing DNS suffixes.

## Network, DNS, access and monitoring

The name is `redis-managed-<project>-<locationSuffix>-<env>-<factorySalt><resourceSuffix>`,
distinct from legacy `redis-...`. A mandatory `${name}-pend` private endpoint uses
the existing project GenAI/default private-endpoint subnet and group ID
`redisEnterprise`. Public network access is **Disabled**, including when
`enablePublicAccessWithPerimeter` or `enablePublicGenAIAccess` is true: these
switches do not make this service public.

The Managed DNS zone is **`privatelink.redis.azure.net`**, not
`privatelink.redis.cache.windows.net` or `privatelink.redisenterprise.cache.azure.net`.
Common DNS and bootstrap inventories include the zone alongside other shared
zones, independently of whether a cache is enabled. Foundation handles upgrades
where the zone is missing and links it to the project VNet. Discovery preserves
an existing link even if bootstrap/customer-owned with a different name. The
new link uses the existing deterministic naming and `NxDomainRedirect` convention.
Noncentral DNS follows the existing VNet resource-group scope (normally the common
RG); the database phase creates only the endpoint's zone group. Failed zone/link
reads are errors, not proof of absence.

With `centralDnsZoneByPolicyInHub=true`, pipelines do not create or inspect hub
DNS zones, links or zone groups. The central DNS owner must provide this exact
zone, client VNet resolution/forwarding and policy-managed `redisEnterprise`
zone groups pointing to it. Adding the zone to bootstrap's inventory does **not**
extend an ALZ initiative's policy coverage automatically. Verify/remediate the
Managed Redis-specific policy before rollout; preflight warns about this external
prerequisite. The endpoint remains private in both modes.

TLS minimum is 1.2; clients connect to the **service-reported host name** on port
**10000**. OSSCluster clients must support Redis Cluster and reach discovered
**85xx** shard ports; do not hardcode shard addresses/ports. Forward the relevant
`<region>.redis.azure.net` namespace through your private DNS resolver.

Access keys are disabled. The existing project managed identity and optional
project service principal receive the supported `default` data-access policy
(full cache command/key access). Entra groups and application/client IDs are not
substituted for principal object IDs; no implicit technical-admin grants are added.
Clients use their principal object ID as username and an Entra token for
`https://redis.azure.com/.default` as password, refreshing before expiry.

No access keys, token secrets, connection-string secret or new Key Vault RBAC
grant is created. Legacy Redis's existing Key Vault secret and one-year expiry
are unchanged. `redisManagedConnection` returns only resource ID, host name,
port, TLS/authentication metadata and clustering policy; it is `{}` when disabled.
Cluster `AllMetrics` and database `ConnectionEvents` diagnostics go to the
existing common Log Analytics workspace.

## Coexistence and migration

Both switches may be true; the resources, private endpoints, DNS zones and
credentials are separate. Enabling Managed Redis does not migrate data or clients,
delete legacy Redis, or reuse its connection-string secret. Plan client/auth,
clustering and data migration, test privately, then cut over explicitly.

Setting the Managed switch false merely skips its **incremental** deployment.
It does not delete a previously deployed cache or its access assignments. There
is no automatic Managed Redis per-service cleanup; deliberate existing whole-project
teardown remains destructive. Unsupported updates fail rather than recreating data.
Static tests/compiler success do not establish live deployment readiness, Entra
token refresh, DNS resolution, NSG reachability, policy/RBAC or service capacity.

## Microsoft references

Validated against Microsoft documentation on 2026-11-07:

- [Cluster API and SKU/capacity semantics](https://learn.microsoft.com/azure/templates/microsoft.cache/2025-07-01/redisenterprise)
- [Database API](https://learn.microsoft.com/azure/templates/microsoft.cache/2025-07-01/redisenterprise/databases)
- [Access policy assignment API](https://learn.microsoft.com/azure/templates/microsoft.cache/2025-07-01/redisenterprise/databases/accesspolicyassignments)
- [Private Link and API-version requirements](https://learn.microsoft.com/azure/redis/private-link)
- [Private endpoint DNS zone values](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)
- [Entra authentication](https://learn.microsoft.com/azure/redis/entra-for-authentication)
- [Architecture, clustering, HA and ports](https://learn.microsoft.com/azure/redis/architecture)
- [Monitoring reference](https://learn.microsoft.com/azure/redis/monitor-cache-reference)
