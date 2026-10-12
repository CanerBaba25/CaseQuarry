# CaseQuarry

**Find the facts. Follow the evidence.**

CaseQuarry is a self-hosted workspace for preserving, searching and reviewing digital evidence. It combines a TypeScript/React interface, a Python API and document parsers, and a Rust command-line integrity engine.

Version **0.1.0** is a working development release for synthetic data and evaluation. It is not production-ready or validated for confidential client matters.

## What works

- Account setup, password authentication, optional authenticator MFA, tenant separation and matter-specific roles.
- Resumable imports of EML, MBOX, text, HTML, CSV, JSON, PDF, DOCX, XLSX, PPTX, images and bounded ZIP archives. Missing OCR and parser errors remain visible.
- Immutable content-addressed originals, SHA-256 verification, duplicate occurrences, attachment families, source spans and raw email dates/headers.
- Boolean and field search, facets, grouping, server pagination, people, communication networks, threads and timelines.
- Human review, tags, notes, saved searches, review sets, issues, tasks and legal holds.
- Audited CSV/JSON exports and reviewed native ZIP packages with manifests, integrity checks and privilege/family safeguards.
- Optional local quotation extraction with verified source citations and human review. It is off by default.
- Authenticated CLI, Rust streaming hash/manifest verification and MBOX preflight, versioned database migrations, and encrypted development backup/restore.

The interface uses live APIs and persisted records. PST/OST, media transcription, external connectors, advanced redaction/Bates production and large-scale search remain unfinished.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24, then:

```shell
uv sync --locked
uv run python scripts/tasks.py setup
uv run python scripts/tasks.py dev
```

Open **http://127.0.0.1:3000/setup**. Enter the generated setup token from your local `.env` and choose your administrator password. Keep `.env` and `.data` private.

For the optional native integrity engine, install Rust and run:

```shell
cargo build --release -p casequarry-evidence-core
uv run cq ingest inventory-mbox path/to/mailbox.mbox
```

The CLI selects the built local engine automatically and provides an explicit Python fallback. It does not download executables while processing evidence.

See [Windows installation](docs/INSTALL_WINDOWS.md), [Linux installation](docs/INSTALL_LINUX.md), [CLI reference](docs/CLI_REFERENCE.md), [reviewer guide](docs/REVIEWER_GUIDE.md) and [administrator guide](docs/ADMIN_GUIDE.md). Container configuration is supplied; Docker/PostgreSQL execution has not been verified on this development machine.

## Verification and limits

A local SQLite benchmark imported **10,000 synthetic emails plus 100 mixed documents** with no failed items. It recorded 10,902 occurrences, 199 duplicate objects and a 245 ms grouped-search p95. Ten image documents were retained with extraction marked partial because OCR was unavailable. See [measured results and limitations](docs/BENCHMARKS.md).

Local automated verification covers authorization, hostile archives, provenance, imports, exports, MFA, migrations, CLI behavior, backup/restore and real browser workflows. Test suites, synthetic generators and browser harnesses are kept local and excluded from this source distribution. Source linting, frontend typechecking/builds and Rust compilation remain available.

The two-million-email target, PostgreSQL behavior, real-model quality, production hardening and disaster recovery are unvalidated. Consult the [threat model](docs/THREAT_MODEL.md), [evidence integrity](docs/EVIDENCE_INTEGRITY.md) and [data handling](docs/DATA_HANDLING.md) before evaluation. Audit hash chains detect local inconsistency; they are not independently signed attestations.

## License and branding

The code is licensed under [Apache 2.0](LICENSE). Modification, independent forks, redistribution and commercial use are permitted under its terms. Dependencies retain their [own licenses](THIRD_PARTY_NOTICES.md). Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md).

The license does not grant general trademark rights. Read the [branding policy](docs/BRAND_POLICY.md) and [preliminary name check](docs/NAME_CHECK.md). No trademark registration or legal clearance is claimed.

CaseQuarry supports professional judgment. It does not provide legal advice, decide privilege automatically, guarantee admissibility or claim regulatory certification. Never post client evidence or secrets in public issues.
