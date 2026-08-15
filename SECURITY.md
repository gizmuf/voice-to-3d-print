# Security policy

Pulsai 3D processes customer API keys, CAD source, uploaded models, generated
artifacts, and manufacturing files. Please do not disclose a suspected
vulnerability in a public issue.

## Reporting

Use GitHub private vulnerability reporting:

https://github.com/gizmuf/voice-to-3d-print/security/advisories/new

Include the affected revision, deployment mode, reproduction conditions,
impact, and the smallest safe proof needed to validate the report. Remove API
keys, customer data, private models, and production credentials. Do not access
another user's project, run destructive tests, create provider cost, or test
production without explicit written authorization.

The maintainer will acknowledge a complete report, validate it, coordinate a
fix, and agree on disclosure timing. Public disclosure should wait until a fix
or mitigation is available to supported users.

## Supported versions

Until the first tagged stable release, only the latest commit on the default
branch is supported. Historical commits, forks, local development overrides,
and deployments that disable the documented public-safe controls are outside
the supported security configuration.

## Security boundaries

- Unsaved customer provider keys remain request-scoped. Explicitly saved keys
  must be account-bound, encrypted at rest with a Secret Manager-backed key,
  never returned to the browser, and must never silently fall back to Pulsai
  billing when secure storage is unavailable or unreadable.
- Public deployments require authentication, owner isolation, private
  artifacts, strict CORS, quotas, and public-safe mode.
- Untrusted Python CAD execution is not supported in the public web service.
- Paid model evals and production security tests require explicit approval and
  a bounded budget.
