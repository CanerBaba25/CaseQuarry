# Contributing to CaseQuarry

Thank you for helping improve CaseQuarry for legal professionals. **Bug reports, feature requests, documentation improvements, tests and pull requests are welcome.**

> **Important**: CaseQuarry intends to be free-to-use and source-available, **not open source**. The proposed license explicitly allows modification in a contribution branch or GitHub fork **for the limited purpose of submitting a change to this original repository**. It does not permit independent modified editions, rebranding, redistribution of adapted builds, or separate hosted versions. The current license is a draft awaiting legal review; maintainers should finalize it and the contributor grant before opening the project for external contributions.

## How to report a problem

1. Search existing Issues to avoid duplicates.
2. File a bug report with the version, environment, exact reproducible steps, expected and actual behavior, safe diagnostic details and sanitized logs.
3. Do **not** attach any real case evidence, client email, personally identifying records, privileged communications, law firm credentials, secret tokens or material under court seal.
4. For sensitive security vulnerabilities, use GitHub private vulnerability reporting or the security contact instead of a public issue.

## How to request a feature

1. Open a Feature Request issue or Discussion in the **original** CaseQuarry repository.
2. Describe the legal workflow problem, user role, expected behavior, privacy or performance constraints and a verifiable acceptance test.
3. Expect maintainers to prioritize based on usefulness, safety and feasibility; submission is not a promise of implementation.

## How to send a pull request (PR)

1. Open or find an issue first for material changes. Discuss scope before implementing large features.
2. Fork the official repo on GitHub, or use an authorized contribution branch directly in it if given write access. The fork is a **Contribution Workspace**, not permission to operate a separate software project.
3. Create a focused branch, such as `fix/threading-bcc` or `feat/evidence-date-filter`.
4. Make the needed changes; use only synthetic test material. Keep reproducible, source-linked evidence behavior and security controls intact.
5. Add tests (unit/integration/authorization), run formatter, lint, type checking, test suite, and relevant background-ingestion smoke tests. Do not make up passing results.
6. Open a **Pull Request to the original CaseQuarry repository's `main` branch**. Fill the PR template with explanation, issue link, test output, migration risk, screenshots if appropriate, and contributor rights confirmations.
7. Update the PR in response to review feedback. Only official maintainers decide whether to merge and ship a change.

## Contribution rules

- Never bypass matter-level authorization, evidence provenance, immutable originals, restricted-data redaction or explicit remote-AI opt-in.
- Do not reproduce competitor project source unless its license truly permits inclusion and the maintainers approve; preserving a compatible third-party copyright notice does not turn that code into CaseQuarry-owned code.
- Verify all contributed code is safe, reviewed and properly licensed.
- Do not use GitHub forks or PR code changes to create independent modified editions, rebrand the project, or present a contributor branch as an official release.
- Contributors retain copyright in their contributions unless separately assigned; before merge, the project needs a valid contributor permission grant suitable for maintaining and licensing official releases. Review `CONTRIBUTOR_TERMS_DRAFT.md` and complete whichever final agreement the project adopts.
- Keep all interaction respectful and on topic.

## Code review and maintainer policy

- Prefer small, reviewable pull requests. Require at least one official maintainer approval, passing checks, secret scanning and relevant tests.
- Require an explicit note for any database migration, evidence export change, permission change or data-retention change.
- Maintain branch protection on `main`, keep release tags signed when practical, and ensure contributions are attributed.
- Review copyright and contribution permission before merging source from new contributors.

## What a fork is — and is not

A public GitHub fork is often necessary to propose changes. CaseQuarry's proposed license authorizes it **for upstream contribution work**. You cannot take the existence of that fork as permission to redistribute a separately maintained, publicly hosted, modified or rebranded product. The original repo remains the canonical release source.

**This contribution workflow and draft license require legal approval prior to launch.**
