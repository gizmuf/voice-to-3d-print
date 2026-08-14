# Security Hardening Proposal: Centralize identity, spend, and artifact authorization

## Decision

We need to decide whether random design ids plus tactical gates are an acceptable
public boundary, or whether durable use requires an authenticated tenant. This
proposal recommends the authenticated boundary before external multi-user use.

## Executive Recommendation

Option 1, **Tactical anonymous containment**, is the immediate safety brake:
platform spend and public artifact publication default off, while free CAD and
BYOK remain available. Option 2, **Required OIDC tenant boundary**, introduces a
principal, one resource policy, atomic quota reservation, and explicit sharing.
I recommend keeping Option 1 during migration and making Option 2 the launch
gate. Option 1 is attractive because it is small and reversible; what gives me
pause is that possession of a design id still grants effective authority.

## Evidence

| Evidence | Finding or document | What it establishes |
| --- | --- | --- |
| `E-AUTH-1` | Anonymous shared ownership | `backend/services/job_store.py` persists `owner_id=anon` and `public=true`. |
| `E-AUTH-2` | Unscoped design access | `backend/app.py` does not bind design operations to a principal. |
| `E-COST-1` | Ambient paid-provider credentials | Provider integrations use process-wide credentials. |
| `E-ART-1` | Public artifact publication | The legacy upload path called `make_public()`. |
| `E-ROADMAP-1` | Product auth and quota intent | `docs/ROADMAP.md` already anticipates auth, billing, quotas, and sharing. |

I inspected the direct callers and persistence boundary. The observed facts
show several separate checks are missing; the structural inference is that
identity and authority have no single owner in the architecture.

## Current Design And Failure Mode

An unauthenticated request can create or name a resource, then use its id on
read, mutation, export, conversation, revision, and artifact paths. The same
process holds provider credentials. Consequently a leaked id can expose a
project, and a public paid endpoint can turn traffic into owner-paid usage.
Public GCS objects extend that exposure beyond the API lifecycle.

## Desired Invariants

- Every durable resource has an owner subject and optional explicit members.
- Authorization evaluates the final design/revision/artifact identity once.
- Paid work starts only after entitlement and atomic quota reservation.
- BYOK cannot fall back to platform billing.
- Sharing is explicit, read-only by default, revocable, and audited.
- GCS objects remain private.

## Constraints And Non-Goals

We preserve local deterministic CAD, slicing, self-hosting, and BYOK. This
proposal does not select a commercial identity vendor or design Stripe plans.
No authentication latency was measured; estimates below are source-derived or
hypothetical.

## Before Architecture

[Before diagram](../diagrams/tenant-authorization-before.mmd)

The important edge is that the API can reach both durable resources and paid
credentials without first deriving a principal or entitlement.

## Options

### Option 1: Tactical anonymous containment

We keep the existing anonymous API but default all platform-paid integrations
and public-object publication to off. Anthropic is available through
request-scoped BYOK, while local CAD, parameter edits, preview, STEP/STL/GLB,
manufacturability, and slicing remain free of model spend. Private objects are
delivered through the backend using random resource locators.

[Option 1 diagram](../diagrams/tenant-authorization-anonymous-containment-after.mmd)

This option is cheap and removes the immediate cost-exhaustion path. It also
reduces accidental indexing of artifacts. It does not create confidentiality:
someone who obtains a design id can still use the API as the owner. The proxy
adds backend egress and availability to artifact downloads. Rollback should
never re-enable public spend on an anonymous endpoint; the safe rollback is to
disable the affected feature.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Provider billing | Ambient platform keys | Disabled unless explicitly protected; BYOK allowed | Stops anonymous owner-paid calls | Legacy paid features fail closed |
| GCS objects | Public/durable URLs | Private objects behind backend path | Removes direct bucket exposure | Extra backend hop |
| Ownership | `anon` | `anon` | No real tenant isolation | None |

### Option 2: Required OIDC tenant boundary

We verify a standard OIDC JWT at the edge and derive a small request principal.
One authorization helper checks owner, member role, or explicit share grant for
the final resource identity. Paid work reserves quota atomically before a job
is accepted; retries use the same idempotency key. Artifact delivery checks the
same policy and then streams privately or emits a short-lived signed URL.

[Option 2 diagram](../diagrams/tenant-authorization-oidc-tenant-boundary-after.mmd)

This is the strongest fit for a hosted product and still lets the open-source
edition support any conforming OIDC provider. It adds an identity-provider
dependency, ownership migration, JWKS rotation, a globally consistent quota
store, and account-support work. We can contain availability risk with cached
JWKS and short token lifetimes, but policy decisions must fail closed. Rollback
requires a pre-migration Firestore/GCS snapshot and keeping Option 1 gates on.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Request identity | None | Verified OIDC subject | Enables enforceable ownership | JWT/JWKS operations |
| Resource policy | Endpoint convention | Central owner/member/share decision | Blocks cross-tenant access | Ownership lookup/cache |
| Quota | None | Atomic reservation before work | Bounds abuse and spend | Global counter service |
| Sharing | Everything effectively public | Explicit revocable grant | Public state becomes intentional | Share lifecycle UI/API |

## Comparison

| Dimension | Option 1 | Option 2 |
| --- | --- | --- |
| Security | Stops platform spend; no ownership | Tenant isolation, quota, explicit shares |
| Performance | Local gates; proxy hop | JWT plus policy lookup |
| Memory | Negligible | Bounded JWKS/policy caches |
| Reliability | Backend required for artifacts | Identity and quota services become dependencies |
| Operability | Small env policy | Key rotation, account and quota operations |
| Migration | Immediate | Anonymous resource migration required |

Option 1 wins only when the service is a private demo or all durable projects
are disposable. Option 2 wins for public users, paid plans, private projects,
teams, or any claim of confidentiality.

## Recommendation

I recommend shipping the tactical gate immediately and treating Option 2 as a
public-launch prerequisite. If the project remains a local CLI/MCP tool with no
hosted persistence, Option 1 could remain sufficient; the hosted website and
collaboration business make Option 2 proportionate.

## Evidence Coverage And Residual Risk

| Evidence | Option 1 | Option 2 | Residual risk |
| --- | --- | --- | --- |
| `E-AUTH-1` — anonymous ownership | Unaffected | Addressed | Account takeover |
| `E-AUTH-2` — unscoped access | Mitigated by random ids | Addressed | Policy implementation bugs |
| `E-COST-1` — provider credentials | Addressed | Addressed | Admin misconfiguration |
| `E-ART-1` — public artifacts | Mitigated | Addressed | Leaked signed/share URLs |

## Migration And Rollout

Keep spend/public-object gates on. Add OIDC in report-only mode, backfill owner
fields only for explicitly claimed designs, quarantine legacy anonymous data,
then enforce reads before writes. Next enforce mutations, exports, artifacts,
and paid jobs. Roll back from a snapshot if owner mapping is wrong; never roll
back by restoring anonymous platform spend.

## Validation Plan

- Cross-tenant matrix for every design, revision, conversation, export, delete,
  and artifact endpoint.
- Provider tests proving denial occurs before network I/O and quota before job
  acceptance.
- JWT expiry, wrong issuer/audience, JWKS rotation, and provider-outage tests.
- Share grant create/read/revoke tests.
- p50/p95 latency and RSS comparison with cold/cached JWKS.
- Backup/restore drill before ownership migration.

## Implementation Work Packages

- OIDC principal and strict production configuration.
- Owner/member/share schema plus centralized authorization helper.
- Atomic quota reservation, idempotency, usage finalization, and alerts.
- Authorized artifact delivery.
- Anonymous-resource quarantine/claim migration.
- Full security and functional E2E matrix.

## Open Questions

- Which OIDC provider is the hosted default while retaining generic OIDC?
- Are anonymous designs ephemeral-only, or disabled?
- Is quota storage Redis, API gateway, or a transactional database counter?
