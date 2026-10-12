<div align="center">

<img src="apps/web/public/favicon.svg" width="64" height="64" alt="CaseQuarry" />

# CaseQuarry

### Find the facts. Follow the evidence.

A self-hosted evidence workspace for legal teams and investigators.

[![Source checks](https://github.com/CanerBaba25/CaseQuarry/actions/workflows/source-checks.yml/badge.svg?branch=main)](https://github.com/CanerBaba25/CaseQuarry/actions/workflows/source-checks.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/CanerBaba25/CaseQuarry?include_prereleases)](https://github.com/CanerBaba25/CaseQuarry/releases)

[Download](https://github.com/CanerBaba25/CaseQuarry/releases) · [Quick start](#quick-start) · [Documentation](#documentation) · [Report a bug](https://github.com/CanerBaba25/CaseQuarry/issues)

</div>

Preserve original files, search across messages and documents, follow conversations,
and record human review decisions in one private workspace. CaseQuarry combines
TypeScript/React for the interface, Python for its API and document processing, and
Rust for streaming integrity checks.

> **Development preview.** Version 0.1.0 is a functioning import, search and review
> release for synthetic data and evaluation. Production use and the two-million-email
> scale target are not validated. It is not cleared for confidential client matters.

![CaseQuarry workspace showing a real synthetic matter, evidence counts and review progress](docs/assets/workspace.png)

*Actual application view using synthetic records. Counts come from persisted API data.*

## What you can do

| Workflow | Available in 0.1.0 |
|---|---|
| Preserve | SHA-256 originals, source paths, MBOX offsets, duplicates and attachment families |
| Import | Resumable uploads and durable jobs with pause, retry, checkpoints and visible errors |
| Search | Boolean/phrase/field/date search, facets, grouping, sorting and server pagination |
| Investigate | People, communication maps, explicit email threads and metadata timelines |
| Review | Versioned decisions, privilege roles, tags, notes, saved searches and review sets |
| Organize | Matters, members, custodians, sources, issues, tasks and legal holds |
| Export | CSV/JSON metadata and reviewed native ZIP packages with verified manifests |
| Secure | Tenant/matter roles, expiring sessions, CSRF, authenticator MFA and audit chains |
| Assist | Optional local source quotations with exact verified citations and human review |
| Operate | Authenticated CLI, Rust integrity tools, migrations and encrypted development backups |

### Supported inputs

**Email:** EML, MBOX. **Documents:** PDF, TXT, Markdown, HTML, CSV, JSON, DOCX,
XLSX and PPTX. **Images:** PNG, JPEG and TIFF. **Archives:** bounded ZIP imports.

Missing OCR, unsupported types and extraction failures remain visible; preserved
originals remain separate from derived text. PST/OST, external connectors, media
transcription, advanced productions/redaction and large-scale ranked search are
still under development.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24.
Python 3.12 is selected automatically by the project.

```shell
git clone https://github.com/CanerBaba25/CaseQuarry.git
cd CaseQuarry
uv sync --locked
uv run python scripts/tasks.py setup
uv run python scripts/tasks.py dev
```

Open **http://127.0.0.1:3000/setup**, enter the generated setup token from your local
`.env`, and choose your administrator password. The API runs on loopback port 8000;
the web app runs on port 3000. Ctrl+C stops both. Data persists in `.data`.

For a tagged source download, use the ZIP and SHA-256 sidecar on the
[Releases page](https://github.com/CanerBaba25/CaseQuarry/releases). Extract the ZIP,
open its directory, and run the same commands starting with `uv sync --locked`.

### Optional Rust tools

With Rust installed:

```shell
cargo build --locked --release -p casequarry-evidence-core
uv run cq ingest inventory-mbox --path path/to/mailbox.mbox
uv run cq evidence hash-file --path path/to/document.pdf
```

The CLI automatically selects the built local engine and supports an explicit
Python fallback. It never downloads a processor while handling evidence.

## Privacy and integrity

- Processing and storage are local by default. Remote model providers are unsupported.
- Local model assistance starts disabled and requires server configuration plus
  explicit matter-lead consent. It cannot change human evidence decisions.
- Originals are immutable through the application; derived text, citations and export
  manifests are independently hash-checked before use.
- Search, retrieval, jobs and exports enforce tenant and matter permissions.
- Privilege, review and integrity safeguards restrict native exports, including
  content embedded in parent email or archive families.
- Audit chains detect inconsistency within the stored chain; they are not independent
  signed attestations.

Keep `.env`, `.data`, evidence, secrets and backups private. Use synthetic material
for evaluation and public bug reports.

## Measured results

The recorded local SQLite run imported **10,000 synthetic emails and 100 mixed documents**:

| Measurement | Recorded result |
|---|---:|
| Preserved occurrences, including attachments/container | 10,902 |
| Exact duplicate occurrences | 199 |
| Failed / unsupported items | 0 / 0 |
| Import time | 163.49 seconds |
| Grouped phrase search p95 | 244.94 ms |
| Peak API + embedded worker memory | 157.20 MiB |

Ten image documents remained partial because OCR was unavailable in that run.
Percentiles use 15 queries; these results are not a production SLA or a multi-million
capacity claim. See [benchmark scope and method](docs/BENCHMARKS.md).

The release passed local Python, Rust and real browser workflow checks, including a
375px mobile view. GitHub verifies source linting, migration setup and Python/web/Rust
builds. Verification suites and synthetic QA harnesses are maintained locally and
excluded from the public source distribution.

## Documentation

| Audience | Guides |
|---|---|
| Install | [Windows](docs/INSTALL_WINDOWS.md), [Linux](docs/INSTALL_LINUX.md) |
| Review evidence | [Reviewer guide](docs/REVIEWER_GUIDE.md), [CLI reference](docs/CLI_REFERENCE.md) |
| Administer | [Administrator guide](docs/ADMIN_GUIDE.md), [Backup and recovery](docs/BACKUP_RECOVERY.md) |
| Assess controls | [Threat model](docs/THREAT_MODEL.md), [Data handling](docs/DATA_HANDLING.md), [Evidence integrity](docs/EVIDENCE_INTEGRITY.md) |
| Assess optional models | [Analysis safety and runtime policy](docs/AI_SAFETY.md) |
| Understand the code | [Architecture](docs/ARCHITECTURE.md), [Release notes](RELEASE_NOTES.md) |

Container configuration is included. Docker/PostgreSQL execution, production
recovery, real-model quality and staged 100k/1m/2m capacity remain unverified.

## Contributing and licensing

Bug reports and focused pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md)
and use [SECURITY.md](SECURITY.md) for sensitive vulnerabilities.

CaseQuarry code is licensed under [Apache 2.0](LICENSE). Independent forks,
modification, redistribution and commercial use are permitted under its terms.
Dependencies retain their [own licenses](THIRD_PARTY_NOTICES.md).

Trademark rights are separate: see the [branding policy](docs/BRAND_POLICY.md) and
[preliminary name check](docs/NAME_CHECK.md). No registration or official registry
clearance is claimed.

CaseQuarry supports professional judgment. It does not provide legal advice, decide
privilege automatically, guarantee admissibility or claim regulatory certification.
