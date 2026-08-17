# Minimal open-source launch plan

The goal of the first launch is evidence, not vanity metrics: real attempts,
reproducible feedback, and a small amount of external participation.

## Success signals for the first 14 days

- 10 people complete at least one real hosted-demo workflow;
- 5 useful feedback reports describe an expected and actual result;
- 2 developers complete a fresh local setup;
- 1 external documentation, test, profile, or code pull request;
- 1 model is reviewed in a real maker workflow, with limitations recorded;
- every public issue receives triage and a clear next state.

Stars and forks are observed but are not targets. Do not trade, buy, or request
empty engagement.

## Day 0 — make the project reviewable

- publish the v0.1.0 alpha release and its known limitations;
- keep CI green and ensure the README demo/setup links work;
- open several genuinely scoped `good first issue` tasks;
- verify that bug and non-coder feedback forms are available;
- prepare one short demo clip later if a clean, non-private workflow is ready.

## Days 1–3 — personal tests

Invite 10–15 people individually across four groups:

- makers or 3D-printing users with a real small part in mind;
- CAD/build123d/Python developers who can evaluate architecture or setup;
- AI/developer-tool users who can assess the agent workflow;
- non-CAD users who can expose onboarding and language problems.

Ask each person for one concrete action: a 10-minute hosted test, a local
install, or review of one issue. Do not ask everyone to star or fork. Reply to
feedback quickly and convert repeated problems into public issues.

## Days 4–7 — one focused public launch

After the first private feedback is addressed, publish one clear post in one
relevant community. Lead with a real workflow and the technical distinction:
editable CAD source and revisions rather than only a generated mesh. Include:

- a one-sentence problem and audience;
- a short demo or before/after model;
- hosted alpha and source links;
- the alpha limitations;
- one explicit request for feedback on the core workflow.

Good launch formats include a Show HN post, a relevant maker/3D-printing
community, or an AI-CAD developer community. Use one first, answer every useful
comment, and only cross-post after incorporating what was learned.

## Days 8–14 — show maintenance

- triage every issue and close duplicates respectfully;
- merge small external improvements with visible review and checks;
- publish v0.1.1 only if there are meaningful fixes;
- record anonymized, verifiable adoption evidence: completed tests, external
  contributors, resolved issues, releases, or documented real workflows;
- use that evidence in grant applications without inflating users or reach.

## Outreach message

> I am testing Pulsai 3D, an open-source parametric CAD studio that turns a
> description or starter model into editable CAD and manufacturing files. Could
> you spend 10 minutes changing one starter model and tell me exactly where the
> workflow is confusing or fails? No coding, fork, purchase, or positive review
> is expected. Demo: https://3d.pulsai.app — source:
> https://github.com/gizmuf/voice-to-3d-print

For developers, replace the hosted-test request with: “Could you try the local
quick start and report the first point where a fresh checkout fails?”
