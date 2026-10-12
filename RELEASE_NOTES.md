# Release notes

## 0.1.0 — October 12, 2026

First working development release for synthetic evidence and evaluation.

### Application

- Connected, responsive evidence workspace with matter dashboards, searchable explorer,
  safe record viewer, review controls, people, threads, network and timeline views.
- Tenant and matter permissions, one-time setup, expiring authentication, optional
  authenticator MFA, CSRF checks and attributed audit chains.
- Durable, resumable EML/MBOX and mixed-document imports with visible errors,
  immutable originals, SHA-256 verification, source labels, mailbox offsets,
  duplicate occurrences, attachment families and versioned text spans.
- Saved searches and review sets, tags, notes, issues, tasks and legal holds.
- Async CSV/JSON/native exports with manifests, fresh authorization/integrity checks
  and reviewed-family privilege safeguards.
- Optional local source quotation extraction with exact validated citations,
  bounded coverage and separate human decisions. Disabled by default.
- Authenticated CLI and optional Rust engine for streaming hashing, manifest
  verification and bounded MBOX inventory, with explicit Python fallback.
- Static database migrations, encrypted development backup/restore, installation
  guides, dependency inventory and Apache 2.0 licensing with a separate brand policy.

### Validation

The complete local Python suite passed 159 tests; 13 real browser workflow checks
passed without page runtime errors, including a 375px mobile view. Local verification
covers API authorization and adverse inputs, ingestion,
review/export integrity, MFA, migrations, CLI, backups and browser interactions.
The web app passes strict TypeScript checks and a production build. The Rust
component passes five tests, formatting, strict Clippy checks and release compilation.
An isolated built Python wheel also migrated a fresh database using only packaged
resources. Final privilege decisions require attorney-level permission to revise
through individual, bulk or tag review routes.

The recorded SQLite run imported 10,000 synthetic emails and 100 mixed documents:
10,902 occurrences, 199 duplicates, zero failed items, 163.49 seconds ingestion,
and 244.94 ms grouped-search p95. Ten images remained partial because OCR was
unavailable. Full measurement scope is in [BENCHMARKS.md](docs/BENCHMARKS.md).

### Distribution

Source, build configuration, license notices and product documentation are published.
Verification suites, synthetic QA harnesses, private drafts, local tooling and runtime
data are excluded. A source ZIP and SHA-256 sidecar are prepared under the local
ignored `.release-artifacts/` directory from the committed tree.

### Remaining work

This is not a complete V1/V2 or production release. Two-million-email capacity,
PostgreSQL/Compose operation, real-model quality and production recovery/hardening
remain unverified. PST/OST and external connectors, media transcription, ranked
large-scale search, advanced production loadfiles/Bates and irreversible redaction
are unfinished. Unsupported production actions fail explicitly.

Trademarks are not registered. Preliminary web name discovery and branding rules
are recorded; official registry clearance remains unverified.
