# Release notes

## 0.2.0 — October 12, 2026

Expanded development preview for synthetic evidence and evaluation.

### Evidence and review

- Real local OCR for scanned PDFs and images, bounded native PDF extraction, and
  Outlook MSG parsing with message metadata and attachment families.
- Explicit retries append immutable extraction versions without replacing originals,
  duplicate occurrences or human review history. Historical citations open their
  exact text version; the reader marks superseded text and prevents review mutations.
- Durable import ownership, live heartbeats and bounded work batches prevent stale
  workers from publishing another worker's result and let other jobs continue during
  expensive extraction.
- Snapshot review assignments with exclusive allocations, claim/release controls,
  progress and versioned completion/cancellation.
- Exact sender/recipient and UTC date filters, a dedicated email reader, scoped
  traffic charts and candidate-only similarities, anchored entities and text comparisons.
- Versioned human issue decisions and task assignments.

### Redaction and production

- Validated text ranges and graphical PDF page regions create irreversible redacted
  derivatives while preserving originals. PDF output is rebuilt from bounded raster
  pages and omits hidden text, annotations, metadata and attachments.
- A different authorized attorney or matter lead must approve redactions and
  productions. Review, privilege, family and hash checks block unsafe disclosure.
- Transactional sequential Bates allocation survives retries and parallel workers.
  Production packages include derived PDFs/text, page images, CSV/DAT/OPT loadfiles
  and hash manifests. They do not include original native files or attachments.
- Native export remains a separate reviewed-original workflow. Production recipient
  import has not been validated; manifests are not digital signatures.

### Account, acquisition and reliability

- Password changes with MFA reauthentication, active session revocation, firm
  administrator account controls and tenant system audit verification.
- Fixed viewer-only search access, authentication status rate limits, stale matter
  displays and upload preflight authorization. Declared and streamed request sizes
  are bounded before parsing, including unauthenticated multipart requests.
- Verified users receive separate API request allowances behind the web proxy;
  login and anonymous limits remain IP-scoped. Managed API launches disable
  untrusted forwarded-header rewriting.
- Case quotas serialize publication of unique originals across queued workers and
  expanded families. Blocked imports can resume after a corrected quota without
  phantom failures or quarantining an otherwise valid archive. Verified duplicate
  uploads, including chunked uploads, consume no additional original-byte quota.
- Expanded authenticated CLI workflows, local folder/Maildir inventories and imports,
  plus explicit read-only TLS IMAP acquisition. No credentials are stored in source.
- Migration `0003_disclosure_workflow` adds the review and production schema without
  modifying previous migration signatures. Run the documented migration before startup.
- Improved GitHub README, real application screenshot and automated verified source
  releases with source ZIPs and SHA-256 sidecars.

### Validation and limits

The complete local Python suite passed 258 tests. Rust passed five tests, formatting
and strict Clippy checks. Focused checks include actual scanned-PDF/image OCR,
immutable retries, competing worker leases, cross-case denials, redaction pixels,
production approval and tamper failures, concurrent Bates allocation and migrations.
Strict TypeScript checks and the web production build passed. A rebuilt source
distribution and wheel were verified in isolation: all 38 packaged Python files
match the final source, and bundled migrations create all 39 database tables.

Browser validation passed 21 end-to-end workflows, followed by two focused checks
after a one-line table layout fix. Approved productions render on desktop; Review,
Analytics and Productions fit a 375px viewport. Signing out and into another account
in the same mounted page exposes no previous-user matter while the new response is
pending. These are two recorded runs, with no page runtime errors.

This remains a development preview. Docker/PostgreSQL execution, live external mail
accounts, recipient loadfile import, real-model quality, production recovery and
100k/1m/2m capacity remain unverified. PST/OST, OAuth mail connectors, transcription
and large-scale ranked search remain unfinished. The published 10k benchmark belongs
to version 0.1.0; it is not a measurement of the new OCR pipeline.

Production rendering is bounded to 50 pages per document and 60 million aggregate
pixels per job. Candidate comparisons use explicitly bounded text and corpus samples;
they cannot establish exhaustive duplicates, collection completeness or verified facts.
See the product guides for additional extraction and acquisition limits.

### Upgrade

Stop the application and preserve a verified backup. Run `uv sync --locked`, then
`uv run python scripts/tasks.py migrate`, and restart using the installation guide.
Downloads contain source, build configuration, license notices and product guides;
local verification suites, runtime data and tooling artifacts are excluded.

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
