# Architecture and release boundary

The development application uses Next.js/React/TypeScript, FastAPI/Pydantic, SQLAlchemy with migrations, private filesystem storage and a durable SQL-backed import queue. Local development uses SQLite; Compose selects PostgreSQL 16 and a separate worker. The browser and CLI use the same versioned authenticated `/api/v1` API.

```mermaid
flowchart LR
  Browser --> Web[Next.js same-origin proxy]
  Web --> API[FastAPI authorization]
  CLI[CLI and OS keyring] --> API
  API --> DB[SQLite development / PostgreSQL Compose]
  API --> Store[Private originals and derived artifacts]
  Worker[Durable SQL worker] --> DB
  Worker --> Store
```

Evidence storage is private; downloads go through authorization and hash verification. Metadata, source occurrences, derived text, review decisions and audit events are separate from original bytes. Deduplication must retain source occurrences and family relationships. Extraction failures retain originals and remain visible in coverage.

Search currently uses scoped SQL keyword/metadata queries and server aggregations. OpenSearch, vector search, RabbitMQ/Celery, enterprise OIDC, Microsoft/Google OAuth collection and multi-million-message capacity are not claimed by this stack. Explicit read-only IMAPS/Maildir acquisition is available through the CLI; validation used a synthetic TLS loopback mailbox. Pagination and streaming are design safeguards; actual throughput and capacity require benchmarks.

AI and remote transmission are disabled by default. Optional local analysis must validate citations against retrieved, authorized text spans and must not change human review decisions. Unavailable adapters/models return explicit errors.

`apps/api/casequarry` contains domain/API/worker code; `apps/cli/casequarry_cli` is the public API client; `apps/web` is the interface; `migrations` tracks schema; public `scripts` contains portable setup, backup, dependency-notice and source-release utilities. Test/fixture/benchmark/browser harnesses remain local and are excluded from public source distributions. Application-level preservation and hash-chain auditing are not tamper-proof against a machine administrator.

PDF text/OCR and MSG extraction use isolated fixed-command subprocesses with bounded output and timeouts. Import claims use a fenced owner nonce, a renewable lease and cooperative record quotas; a dedicated import slot allows exports and production work to progress during slow extraction. Parsing occurs outside SQL writer transactions and authorization is checked before publication. See [adapter limits and acquisition behavior](ADAPTERS.md).

Shipped API launch commands disable Uvicorn proxy-header rewriting explicitly. General rate limits use verified tenant/user identity; anonymous and sign-in limits use the actual transport peer. Forwarded headers do not establish identity. A future production reverse-proxy deployment must configure and validate its trusted network boundary explicitly before enabling forwarded-header handling.

The optional Rust evidence core provides bounded streaming SHA-256, native-package manifest verification and MBOX preflight. The CLI invokes a fixed locally built binary through an operation allowlist without a shell; Python fallbacks keep these local diagnostics available when the binary is not built. It does not replace server-side matter authorization or MIME/document parsing.

The published 0.1.0 baseline and working reviewer extensions use Apache-2.0. Confidential deployment, production recovery/redaction interoperability, practitioner QA and larger capacity claims remain release gates until their exact tests and reviews are recorded. The local 10k SQLite trial is documented in [benchmarks](BENCHMARKS.md); it proves its recorded scope only and predates the isolated parser extensions.
