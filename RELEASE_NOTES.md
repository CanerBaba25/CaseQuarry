# Release notes

## 0.5.0 — October 13, 2026

Daily review improvements with task details, conflict-safe team edits and lighter
evidence listings. Includes the website/server packages and Windows, universal Mac
and Ubuntu 24.04 x64 desktop installers.

### Tasks and evidence navigation

- Open task details from My work or a matter's task list. Edit title, description,
  status, assignee and due date with current membership checks and audit history.
- Read full task details and the current version with `cq task show`; CLI edits
  forward the explicitly supplied version and preserve conflict errors without retry.
- Filter My work by open/in-progress status as well as deadline. Counts cover the
  full authorized scope. Saves carry a task version; conflicting saves keep the
  draft and require an explicit reload or comparison/rebase.
- Task ordering revisions detect delayed creation commits and status-filter changes.
  A changed paged worklist restarts instead of silently skipping tasks.
- Previous/next evidence buttons follow the visible page's order and stop at its
  boundaries. Unsaved tag/note drafts block those buttons until saved or cleared.
- Copy a source link for an exact extraction version and text anchor. Links require
  existing matter permission and open cited versions read-only.

### Performance and consistency

- Evidence listing queries select display fields and compute 300-character snippets
  in SQL. Full source text and extraction/email metadata are read when opening details.
  In a synthetic 1,000-record PostgreSQL comparison, a 50-item page avoided about
  5.7 MB of unused text/metadata loading; median whole-search time over seven warmed
  samples changed from 29.4 ms to 9.2 ms. All 39 comparison responses matched, and
  the query count stayed at seven. This is a scoped measurement, not a scale claim.
- Evidence rows now refresh after committed changes from another connected client.
  Scope-clearing events and denied reads remove cached results; expired sessions
  clear private views and return to login.
- Matching refresh/clear events synchronously abort pending resource reads, preventing
  queued older responses from restoring cached data before effect cleanup.
- Initial and changing evidence routes use their actual URL query directly, avoiding
  a search with old or default filters before the requested scope is ready.

### Validation

The complete local backend suite passed 424 tests with PostgreSQL checks enabled
and no skips. Thirteen new task/evidence browser workflows and all 25 existing
browser workflows passed without runtime errors. Checks include actual concurrent
edits, held response barriers, cross-client review refresh, source-linked read-only
views and account isolation. Web typechecking and production builds passed; the
Rust core and Windows desktop passed five and eight tests respectively. The local
Windows installer passed three isolated install/launch/uninstall checks with
existing account data and registry state preserved.

The release workflow builds and verifies every native platform and both server
packages before publication. Installed PostgreSQL server checks and Intel/Apple
Silicon/Ubuntu system WebView checks remain release gates.

### Upgrade and limits

Stop the server, preserve a verified database/evidence backup, upgrade dependencies
and run `uv run python scripts/tasks.py migrate`. Migration `0007_task_versions`
backfills existing tasks without changing their titles, assignments or due dates.
Reload open browser/desktop workspaces after upgrading: task PATCH requests require
`expected_version`. See [the task API](docs/TASK_API.md).

Windows remains unsigned and Mac remains non-notarized. Clients require a reachable
firm server. Production scale, live provider accounts and offline editing retain
the limitations documented in 0.4.0.

## 0.4.0 — October 13, 2026

Installable web and desktop release with a redesigned daily workspace, personal
timezones and manual task deadlines.

### Workspace and tasks

- Refreshed light/dark interface with grouped navigation, clearer tables, responsive
  controls and card/list matter views. README images show the actual website and
  native desktop connection screen.
- Keyboard command palette searches all accessible server matters, including optional
  archived matters, with signed pagination and keyboard selection.
- My work orders assignments by their nearest deadline across matters. Overdue,
  next-seven-day and undated filters have counts across the full authorized scope.
  Complete authorized tasks directly from the dashboard.
- Create, edit and remove manual task due dates. Dates remain calendar dates and
  are never calculated court deadlines. Changing a deadline or assignment invalidates
  an older worklist ordering cursor instead of silently skipping rows.
- Each user can search IANA timezones, save a preference or use the device timezone.
  Preferences persist on the firm server across clients. Timestamp display and task
  day classification use that preference; date-only deadlines retain their entered
  date. The server uses a pinned timezone database on every operating system.

### Permission and consistency fixes

- Matter and task lists now enforce current active account and valid membership permissions
  in the same query that reads the returned data.
- Task views immediately clear cached details after access-denied responses.
- Concurrent account deactivation and team changes cannot remove a matter's last
  active lead. Legal-hold changes share the matter lock used by archive operations.
- Transactional task-order revisions detect deadline and assignment changes even
  when the editing transaction commits after a worklist snapshot was opened.
- Restored spacing in account/session/provider controls and fixed refresh events
  without payloads. Existing provider consent and source-integrity controls remain.
- Successful review saves update the displayed revision immediately, preventing a
  following tag save from sending the previous revision before a background refresh.
  Background reads preserve unsaved tag drafts, and switching evidence isolates
  pending save messages from the newly opened item.

### Desktop and distribution

- Windows x64 NSIS installer, universal macOS DMG for Intel and Apple Silicon, and
  Ubuntu 24.04 x64 DEB. All clients connect to the same PostgreSQL-backed firm server.
- Windows URL preferences use DPAPI; macOS/Linux use private account files with
  permission and symlink checks. No provider key, password or evidence is stored
  in these connection preferences.
- Release assets include three desktop installers, built Windows/Linux web-server
  ZIPs, a source ZIP and a SHA-256 sidecar for each package. The release is regular,
  not marked as a prerelease.
- Build checks install and launch the Linux DEB, mount and launch the same universal
  DMG on Intel and Apple Silicon runners, and launch the Windows system WebView.
  Native diagnostics use isolated preferences and check the connection screen;
  browser acceptance separately checks authenticated firm workflows.
- Dependency notices cover all four desktop architecture targets and preserve
  full applicable license texts. Server packages include the required notices and
  corresponding native-library source material.

### Validation and limits

The complete local Python suite passed 378 tests, with ten skipped in that run.
An additional 89 focused checks ran against actual PostgreSQL, including delayed
commits, last-lead races, legal holds, timezone boundaries and populated upgrades.
The native Windows client passed eight Rust tests, formatting and lint checks,
an actual WebView runtime diagnostic and three isolated install/launch/uninstall
checks. Browser validation covers the new workspace, deadlines, timezone persistence,
server-wide navigation, mobile layout and existing evidence workflows.

The Windows installer is unsigned and the Mac app is not notarized. Follow the
platform guide for installation approval. Ubuntu 24.04 x64 is the packaged Linux
target; other distributions and physical device combinations are not certified.
Clients require a reachable firm server; offline editing is unavailable. Paid vendor
accounts, model quality, Docker runtime operation, production recovery and
100k/1m/2m capacity remain unvalidated. The earlier SQLite benchmark is unchanged.

### Upgrade

Stop the application and preserve a verified database/evidence backup. Upgrade the
dependencies and run `uv run python scripts/tasks.py migrate` before restarting.
The forward migrations are `0005_task_due_dates` and `0006_user_time_zones`;
existing users start with UTC and existing tasks have no deadline. Startup refuses
a stale schema. Preserve provider encryption keys and private server configuration.
Follow the guarded transfer guide for older SQLite installations.

## 0.3.0 — October 12, 2026

Installable web and Windows desktop release with a shared PostgreSQL firm server.

### Desktop and collaboration

- Installable Rust/Tauri Windows x64 client with a firm connection screen, strict
  HTTPS origin checks and a separate restricted workspace WebView. Connection
  preferences contain only the server URL and are protected with Windows DPAPI.
- Browser and desktop clients use the same server, PostgreSQL database, evidence
  storage and account/matter permissions. Connected matter views refresh on committed
  changes and import progress. Revoked access clears the mounted matter.
- A personal My work dashboard lists open assigned tasks across accessible active
  matters with stable pagination and automatic refresh. Completed tasks remain in
  their matter history.
- Matter navigation now supports signed, account-scoped pagination and server-side
  title/client/number search, avoiding the previous first-100-matters limit.

### Optional provider connections

- User-owned OpenAI, Google Gemini, xAI Grok and Anthropic Claude API keys with
  encrypted, scope-bound storage, masked readback, versioned edits and revocation.
- External processing requires active firm approval, current matter-lead consent,
  the requester’s own connection and confirmation with a purpose for every job.
  Saving keys or importing evidence makes no provider request.
- Bounded official HTTPS transports, safe provider errors and verified exact source
  quotations. Workers recheck keys, policies, permissions, privilege and source
  integrity before transmission and publication. No automatic paid retries.

### PostgreSQL and distribution

- PostgreSQL is the default database, with managed local setup, explicit schema
  migration and a guarded SQLite transfer that preserves the source and verifies
  copied rows and evidence before enabling the target.
- Fixed PostgreSQL Decimal quota totals that could break import failure reporting,
  and fixed preview reads incorrectly triggering shared-client refreshes.
- Release assets include the Windows desktop installer, built Windows/Linux web
  server packages, source ZIP and SHA-256 sidecars. Packages carry the project and
  applicable third-party license notices.
- Standalone server packages include pinned image-library source archives, build
  recipes, patches and complete notices for their bundled native/WASM libraries.
  Microsoft’s WebView2 bootstrapper is downloaded directly during installation when
  needed, with its own prerequisite UI and terms; it is not included in the desktop binary.

### Validation and limits

The complete local Python suite passed 337 tests. Real PostgreSQL acceptance covered
imports, queued/concurrent quotas and immutable
reprocessing. The complete browser run passed 25 workflows, including provider key
handling, shared task refresh, review, productions, mobile views and account isolation.
Seven focused browser checks additionally verify firm/matter/per-job consent, mobile
provider settings, shared worklists, live membership revocation and matter search.
External confirmation resets after scope changes and every submitted or failed request;
an unchecked retry cannot transmit evidence.
Native Windows verification passed seven Rust tests and 12 actual WebView2/installer
checks, including PostgreSQL-backed login, remote IPC denial, install and uninstall.
Cloud/local adapter checks passed 94 focused tests, with two actual API checks also
run on PostgreSQL. These use controlled provider HTTP responses; no paid vendor
request or real account/model compatibility claim is made.

Six independent PostgreSQL transfer checks verify every row across all 39 legacy
tables, original bytes, review history, audit chains and cyclic foreign keys. Tampered
originals, linked source files, mismatched storage roots and populated targets are
refused; invalid audits roll back the complete copy while retaining the legacy source.

The Windows server ZIP passed a fresh isolated runtime installation and four actual
PostgreSQL workflows covering migrations, authentication, shared-client matters,
worker imports, exact original bytes and revision updates. Distribution checks wait
for API readiness and use the installed private runtime on each operating system.

The Windows installer is unsigned. Clients
require a reachable firm server; offline editing is unavailable. Production recovery,
Docker runtime operation, recipient loadfile import, real-model quality and
100k/1m/2m capacity remain unvalidated. The earlier SQLite 10k benchmark is unchanged.

### Upgrade

Stop the application and keep a verified database/evidence backup. Upgrade dependencies
and run migration `0004_firm_sync_providers` through the documented migration command.
For older SQLite installations, use the guarded transfer before changing the database
URL; do not replace or discard the legacy database. Preserve the provider encryption
key privately with recovery material. See the installation and provider guides.

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
