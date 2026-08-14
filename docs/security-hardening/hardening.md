# Security Hardening Review: Pulsai 3D multi-user boundary

## Evidence Basis

I inspected the public API, Firestore/GCS persistence, provider credential
paths, and product roadmap at Git HEAD `b6d6568` plus the current working-tree
patch. The evidence is source-derived; no authenticated production tenant test
was possible because accounts do not yet exist.

## Constraints

We must preserve zero-cost deterministic CAD, fast preview/build/slicing, BYOK,
and an easy self-hosted open-source path. Platform provider credentials must not
be ambient authority for anonymous requests. Public sharing must become an
explicit resource state rather than the default.

## Opportunity Portfolio

| Opportunity | Evidence | Options | Recommendation | Proposal |
| --- | --- | --- | --- | --- |
| Centralize identity, spend, and artifact authorization | Anonymous ownership, unscoped design access, public artifacts, shared provider credentials (`E-AUTH-1`, `E-AUTH-2`, `E-COST-1`, `E-ART-1`) | 1. Tactical anonymous containment; 2. Required OIDC tenant boundary | Use Option 1 only as the immediate safety gate; move to Option 2 before inviting external users. | [Tenant authorization proposal](proposals/tenant-authorization.md) |

## Recommendation Summary

The current patch is a useful emergency brake: it defaults platform spend and
public GCS publication to off while preserving local CAD and customer BYOK. It
does not solve ownership. I recommend a vendor-neutral OIDC boundary with one
central authorization decision for every design, revision, artifact, export,
and paid operation. This costs one JWT verification and one ownership lookup on
most API requests, but it turns a guessed or leaked design id from authority
into an ordinary identifier.

## Next Decisions

- Select the first production identity provider implementing standard OIDC.
- Decide whether anonymous users may create ephemeral local-only designs or
  whether all durable writes require sign-in.
- Select a global rate-limit store (managed Redis, API gateway, or equivalent).
- Define free, BYOK, and hosted-compute quotas before public launch.
