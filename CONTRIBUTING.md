# Contributing to Pulsai 3D

Thank you for helping make open, editable CAD easier to use. Contributions from
makers, designers, technical writers, testers, and developers are welcome.

## Ways to help

- Try the [hosted alpha](https://3d.pulsai.app) and submit structured feedback.
- Reproduce a bug and add the smallest safe test case.
- Improve setup, CAD, printer, or user documentation.
- Add or verify a printer profile with a focused test.
- Work on an issue labeled
  [`good first issue`](https://github.com/gizmuf/voice-to-3d-print/labels/good%20first%20issue).
- Propose a larger feature after discussing its scope in an issue.

Non-coders can use the
[10-minute testing guide](docs/HELP_WITHOUT_CODING.md). A clear report from a
real workflow is a meaningful open-source contribution.

## Before you start

1. Search existing issues and pull requests.
2. For anything larger than a small fix, open or comment on an issue first.
3. Keep the change focused on one problem.
4. Do not run paid provider calls unless you are using your own authorized key
   and have set a budget.

Use the local setup in [`README.md`](README.md) or the detailed Linux runbook in
[`docs/RUNBOOK_LINUX.md`](docs/RUNBOOK_LINUX.md).

## Pull requests

A good pull request:

- explains the user problem and the chosen change;
- includes tests or a reproducible manual check appropriate to the risk;
- preserves the deterministic, no-paid-AI validation path;
- does not mix unrelated cleanup or dependency upgrades;
- updates documentation when behavior changes;
- passes `git diff --check` and the relevant backend/frontend checks.

For CAD changes, “done” means the geometry or artifact changed as intended, the
revision/mesh evidence was updated, and the current preview was checked. A
successful API response alone is not enough.

## Data, secrets, and provenance

Never include API keys, tokens, customer projects, production logs, private QA
media, personal information, or non-public model files. Do not submit code or
assets copied from CAD viewers, model libraries, generated datasets, or other
projects unless the license is compatible and the provenance is documented.

Report suspected vulnerabilities privately as described in
[`SECURITY.md`](SECURITY.md), not in a public issue.

## Contribution licensing

Unless a separate written agreement says otherwise, contributions accepted into
this repository are provided under the repository's
**AGPL-3.0-or-later** license. Commercial licensing of maintainer-owned code is
separate; contributor work is not relicensed without the contributor's
permission or another applicable agreement.

The project may introduce an explicit contributor agreement for future changes
that need dual-licensing rights. If that happens, the requirement will be stated
before such a contribution is merged.

By participating, you agree to follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
