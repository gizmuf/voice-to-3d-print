# Open-source and product strategy

## Recommendation

Pulsai 3D should be both a visual application and an agent tool. The website
owns the interactions that are intrinsically visual: orbit/select, parameters,
revision comparison, manufacturability markers, orientation, slicing, and file
downloads. A headless MCP/CLI adapter should expose the same CAD engine to
Codex, Claude Code, and other compatible harnesses. The harness is a
distribution channel and automation surface, not a replacement for the viewer.

Recommended product shape:

```text
Open CAD engine + contracts
├── Web studio (reference UI and managed SaaS)
├── MCP server (Codex/Claude/other clients)
├── CLI / Python SDK
└── Worker API (build, inspect, slice, export)
```

## Sustainable business model

- Free/open-source self-hosting with user-owned provider keys.
- Managed cloud subscription for accounts, private storage, collaboration,
  backups, queues, observability, and no-setup CAD/slicing workers.
- Usage-based hosted compute for CAD builds, image/mesh providers, and future
  simulation/CAM workers.
- Team/enterprise plans for SSO, private deployment, audit logs, policy,
  support, and commercial licensing.
- A public design/gallery ecosystem can drive discovery, but publishing must be
  explicit and private projects must remain private by default.

The owner selected **AGPL-3.0-or-later** for the hosted core. The canonical
license text is now in `LICENSE`. A separate commercial license can be offered
to customers that cannot use AGPL. Before accepting external contributions for
a dual-license model, establish a contributor agreement that preserves the
right to relicense those contributions.

Compared with MIT: MIT is permissive and allows a third party to create a
closed hosted fork while retaining only the short copyright/license notice.
AGPL permits commercial use too, but a party offering a modified version over
a network must offer corresponding source to that service's users. The AGPL
does not automatically apply to CAD files created by users, and it does not
grant rights to the Pulsai trademarks.

## OpenAI Codex for Open Source

The current official program offers selected maintainers six months of ChatGPT
Pro, possible API credits for maintainer/core OSS workflows, and conditional
Codex Security access. It does not promise six monthly payments of USD 200.
The repository and maintainer profile must be public, and selection considers
usage, ecosystem importance, adoption, and evidence of active maintenance.

Official application: https://openai.com/form/codex-for-oss/

An application will be stronger after the repository has a real license,
reproducible setup, CI, public issues/releases, a focused README/demo, and early
external users or contributors.

## Public-release gate

- License selected and added; keep the trademark/branding boundary documented.
- Scan all Git history and release artifacts for secrets; rotate any exposed
  credential before publication.
- Remove product-crossing URLs, private paths, internal account identifiers,
  and production-only configuration.
- Add `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, support policy,
  architecture, and a public roadmap.
- Require BYOK or an authenticated entitlement for every paid provider.
- Require private-by-default projects/artifacts and tenant authorization before
  offering the hosted multi-user service.
- Pin dependencies and run Linux CI plus the free CAD-to-print E2E.
- Publish a clean tagged release from a reviewed commit, then change GitHub
  visibility. Do not expose the current working tree directly.

Current status: repository `gizmuf/voice-to-3d-print` is public under
AGPL-3.0-or-later. History and staged secret scans passed before publication,
documented public-safe defaults are in place, and CI covers backend, frontend,
STT, secret scanning, and a free CAD-to-print flow. The next OSS gate is the
v0.1.0 alpha release, followed by real-user feedback, public issue triage, and
small external contributions.
