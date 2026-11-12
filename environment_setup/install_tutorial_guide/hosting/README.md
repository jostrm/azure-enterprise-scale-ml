# Protected tutorial preview hosting — approval required

This is a design/operations handoff, **not a deployment**. No working credentials,
license keys, provider paths or live host are included. `example.invalid` endpoints
are deliberate nonproduction placeholders. Host selection, cost, DNS, TLS ownership,
signing identity and production policy remain owner approval decisions.

## Small initial topology

One ASP.NET Core 10 process behind an approved HTTPS endpoint; no database initially.
The native client receives only the public `PreviewApiBaseUri` (see
`previewsettings.example.json`), never provider credentials or an administrative key.
The public environment override is `ESAIF_PREVIEW_API_URL`. The native gate label is
**Preview Code To Enter**. Server validation of an approved code unlocks all enabled
tutorials; an unknown, missing, expired or revoked code must not grant access.
Server-side secret storage and safe admin access must be approved independently.
Bind the service privately/loopback behind the TLS ingress; reject untrusted forwarded
headers. Restrict management routes and avoid logging license/session/media secrets.
Do not create a public admin endpoint merely for operational convenience.

The service owns the protected tutorial root, validated video catalog and opaque
media-reference/provider mapping. These files are **not** public hosting static assets.
Do not expose a static tutorial directory, provider paths or arbitrary proxy URLs.
Only bounded read operations scoped to the current entitlement are appropriate.
Protect catalog, guide, image, caption and media-link responses equally; configure
`Cache-Control: no-store`. No offline disk cache is supported.

## Sessions and policy

Use high-entropy session tokens and retain only their hashes in the initial in-memory
session registry. **Restart revokes every session** and requires sign-in again.
There is no durable license store or multi-instance coordination in this initial
design. Run one instance; do not assume load-balanced replicas share revocation state.
Production support must explicitly choose license lifetime, session lifetime and
renewal/revocation behavior. There is **no chosen default production lifetime**.
Any dev-only short lifetime is a test policy, not commercial terms.

Before approval, verify that expiry/revocation/invalid tokens reject protected
requests and clear client UI/media state, that an interrupted server fails closed,
and that no license key/token persists in local progress files or request logs.
Catalog completeness is a separate release gate: schema-valid empty metadata does
not mean any of the six scenario recordings have been delivered.

## Dropbox temporary-link limitation

The official
[files/get_temporary_link API reference](https://docs.dropboxapi.com/dropbox-api/api-reference/user-endpoints/files/get-temporary-link)
(checked 2026-11-09) states that returned links expire in **four hours**, then return
**410 Gone**. This provider lifetime is not a configurable short entitlement TTL.
Do not describe a previously issued link as revoked when the app license expires.
Stopping/clearing native playback and refusing new links limits client behavior but
does not invalidate a link already received. Authorized viewers may retain bytes or
record their screen; this preview is not DRM.

If commercial policy requires stronger immediate revocation than the provider's
four-hour window, do not approve direct-link delivery. Review a server-authorized
stream/proxy or a media service with shorter controlled URLs, including range
requests, throughput, egress cost, concurrency and logging. Such infrastructure
and spending are **not authorized or provisioned** here.

Provider tokens, refresh tokens and path mappings remain server-side. Do not copy
them into the app, release JSON, screenshot, support email or catalog example.
Use mediaRef identifiers to resolve only approved media; never accept arbitrary
URLs or filesystem paths from a client.

## Approval checklist

1. Owner chooses hosting region, operator, single-instance capacity, costs and budget.
2. Owner supplies production lifetime/revocation policy and approves any provider
   link exposure window.
3. Operator configures HTTPS, server secrets and private approved content in the
   API project's actual documented configuration contract; this directory does not
   invent a working service configuration or credentials.
4. Validate six real primary recordings against the chosen tutorial manifest;
   verify actual playable media, rights, titles, measured durations and captions.
5. Test sign-in, expiry, revocation, restart, missing assets, seek/range support,
   native codec failures and no-store behavior without logging secrets.
6. Supply the approval reference to the packaging chain. Publishing the EXE,
   operating the host and granting licenses each require their own authorization.

No commands in this directory deploy a service or create a domain, subscription,
database, secret or paid resource.

## Unresolved hosting decision

Simply.com is an option to evaluate, not an assumed deployment target: the user's
actual plan, support for an always-running ASP.NET Core 10 process, private content,
environment/secret configuration, logs, restart behavior and HTTPS termination are
unverified. A static/shared PHP hosting plan is not evidence of .NET process support.
Ask the provider for the exact plan capabilities before selecting it. Costs are
**unknown** until the plan, storage, media bandwidth and region are confirmed.
No price, purchase, deployment or domain change is implied.
