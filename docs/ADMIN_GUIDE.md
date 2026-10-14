# Administrator guide

This guide covers the implemented 0.8 controls. PostgreSQL is the shared database for browser and desktop clients. Real PostgreSQL migrations, import workflows and separate-client updates have been exercised; Docker runtime operation and production recovery remain unvalidated. Use a synthetic evaluation corpus until the host, access policy, preservation and reviewer workflow are approved for the intended deployment.

## Install and bootstrap

Follow the [firm server](SERVER_INSTALL.md), [Windows](INSTALL_WINDOWS.md) or [Linux](INSTALL_LINUX.md) installation guide. Install [desktop clients](DESKTOP.md) on workstations as needed and give them the same trusted HTTPS firm URL. Keep `.env` and evidence storage private, owner-restricted and outside source control. The one-time setup token expires; setup creates the first firm administrator and requires a new password. Replacing an expired token does not require deleting an existing database.

Use an encrypted host and storage location that matches the matter's data policy. A local application process does not prevent a cloud-sync client from uploading its files. Configure `CASEQUARRY_STORAGE_ROOT` to a protected location when `.data` is inappropriate.

For deployment, terminate HTTPS through the configured service boundary, use `CASEQUARRY_ENVIRONMENT=production` so cookies are secure, and ensure only authorized clients can reach the application. Do not expose the database, worker or private object store directly. Development loopback cookie settings are for the local workflow.

## Apply the versioned schema

The release schema is `0010_manual_hold_notices`, following `0009_user_language`.
It adds a separate notice register without changing existing holds or evidence.
Migrations ship in the Python package and source distribution; apply the forward
migration before starting the upgraded server.

With services stopped and a verified backup available, run from the project environment:

```sh
uv run python -m casequarry.database migrate
uv run python -m casequarry.database status
```

The configured database URL comes from environment settings; these commands do not print its credentials. Migrations serialize across processes using a SQLite write lock or PostgreSQL advisory transaction lock. Current revision and frozen schema are validated before upgrading. Existing data is retained during the core-to-analysis-to-disclosure upgrade path.

Development startup may adopt an **exact known** unversioned development schema. To perform that explicitly, use `migrate --adopt-existing-development`. Unknown columns, types, constraints, indexes or revisions cause refusal without silently stamping the database. Production startup never adopts or migrates a schema automatically: apply the operator migration first. Preserve a schema-drift diagnostic and reconcile it against the installed release before restarting; do not drop evidence tables as a repair step.

## Manage accounts and matter access

Firm administrators manage user accounts and configuration. Matter membership controls content access independently:

| Matter role                | Relevant workflow permissions                                                                                                                             |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Matter lead                | Import, review, assignments, export, holds, final privilege and separate disclosure approval. Only the lead can consent to matter-local model processing. |
| Attorney                   | Import, review, export, holds, final privilege and separate disclosure approval.                                                                          |
| Review manager             | Import, review, assignments and export; cannot make final privilege decisions or approve disclosure as attorney/lead.                                     |
| Reviewer                   | Evidence review and assignment claim/release/completion within the allocation rules.                                                                      |
| Expert, read-only, auditor | Authorized matter viewing; the auditor also has matter audit access. These roles do not gain review/export permission automatically.                      |

Create a second matter lead or attorney for independent redaction and production approval. The requester cannot approve their own disclosure, even if they are also a firm administrator. Verify boundaries with separate accounts before using a matter operationally.

Account administration uses the expected current account status and role to detect concurrent changes. The application blocks self-deactivation/self-demotion and removal of the last active firm administrator. Deactivation and account-role changes revoke existing sessions; matter roles remain explicit memberships. Jobs recheck the requester's active account and current matter permission before publication, and disclosure downloads also recheck their approver.

Users can list and revoke their own active sessions, change passwords and enroll authenticator MFA. Password changes require the existing password and, when enabled, a valid authenticator code; all other sessions are revoked. Session expiry and browser CSRF checks remain enforced on localhost. Tenant system audit records account/session changes separately from matter-content events.

## Operate imports and extraction

Check the matter's installed adapter readiness before import. OCR requires a trusted local Tesseract executable and installed language data; the application does not download them during document parsing. Supported Outlook MSG extraction is bounded and isolated; PST/OST, media transcription and unconfigured Gmail/Microsoft 365 OAuth remain unavailable. See [adapter settings and acquisition limits](ADAPTERS.md).

Defaults include a 256 MiB upload limit, 200 files per batch, 2,000 archive entries, a 512 MiB expanded archive budget, expansion ratio 100, nesting depth 3 and four million extracted characters. Recognition defaults are 200 pages, 25 million pixels per page and 60 seconds per page. Keep limits aligned with host memory, storage and reviewer capacity.

Monitor actual job states, preserved/searchable/partial counts and errors. Pause, resume and cancel affect durable checkpoints. Explicit retry is available for failed or partial batches after a runtime, setting or source problem is repaired. Reprocessing verifies the same originals and appends immutable artifact/span versions without duplicating source occurrences or erasing human reviews. Changed extraction should be inspected before relying on earlier review. Quarantine is not automatically released by retry.

Import ownership uses a renewable two-minute lease and an owner nonce. Parsing occurs outside SQL write transactions; publication rechecks ownership and authorization. A configurable record quota, default 25, preserves MBOX offsets while allowing other jobs to run. One background import slot allows exports, redactions, productions and optional local analysis to progress during extraction.

`CASEQUARRY_ANTIVIRUS_COMMAND` enables a configured scanner before extraction. A detection quarantines the original; scanner failure prevents parsing. An absent scanner must not be represented as a completed clean scan. Verify the scanner's installation and command semantics on the actual host.

## Configure review and disclosure workflows

Assignments contain fixed 1–500-item snapshots with exclusive active allocations. Review managers or leads create them; active review-authorized members can claim unassigned entries. Completion requires every item to be responsive or non-responsive and uses version checks. Completing an allocation is not a final privilege clearance.

Redaction and production records are separate from preserved originals. PDF redaction uses a fixed local renderer subprocess without JavaScript/XFA support, builds fresh lossless image-only PDFs and verifies their structure and pixel bytes. Text requests remove selected character ranges from verified UTF-8 extraction. Every ready redaction and production proposal requires a different current attorney or matter lead to approve it. Human inspection must identify all needed regions/ranges; the renderer does not discover every sensitive occurrence.

| Disclosure limit              | Implemented boundary                                                                                                                              |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Production selection          | At most 200 evidence items; explicit IDs, review-set snapshot or query snapshot.                                                                  |
| PDF original / document       | At most 50 MB, 50 pages and 40 million rendered pixels.                                                                                           |
| PDF preview / render deadline | 30-second isolated preview or 90-second flattening subprocess.                                                                                    |
| Aggregate production          | At most 60 million rendered pixels and 250 MB of produced document/image bytes.                                                                   |
| Text derivative               | Complete indexed text up to 2 MB; partial/unavailable extraction is held back for text delivery.                                                  |
| Redaction selection           | At most 200 normalized PDF rectangles or non-overlapping text ranges.                                                                             |
| Bates registry                | Prefix up to 16 uppercase characters, beginning with a letter; eight-digit numbers allocated per matter/prefix, never recycled after reservation. |

Production is derived-only PDF/text, with preserved source and parent IDs, original/produced hashes and an explicit load-file profile. Native ZIP exports are separate and include original bytes, requiring review of embedded descendants. They are not a redacted-delivery substitute.

Unreviewed/needs-review, suspected/confirmed privilege and quarantine block production. Changes to source bytes, extraction/review version, redacted derivative or current requester/approver access invalidate delivery. Mixed redacted and unredacted copies of the same original are blocked. Active legal holds preserve originals and block matter archival where required; they do not grant disclosure authority. Hold activation/release require an authorized lead/attorney and an audited reason; released holds are not silently reactivated.

Load files use a documented CSV, UTF-8 DAT delimiter and ASCII Opticon profile with single-page flattened PDF references. Internal fixtures validate the mapping and package hashes; no recipient review-platform import has been executed. Test that profile with the intended recipient before delivery. SHA-256 verification is not a digital signature, independent timestamp or external custody anchor.

Version 0.8 optionally adds [Ed25519-signed ZIP manifests](SIGNED_EXPORTS.md) with
a dedicated `CASEQUARRY_EXPORT_SIGNING_KEY_FILE`. Keep the private key outside
source control, distribute trusted public keys independently and retain historical
public keys across rotation. Invalid configured keys fail closed; CSV/JSON exports
remain unsigned. Signing does not change the approval or preservation rules.

Use the [custodian notice register](HOLD_NOTICES.md) to record staff-managed
issuance, acknowledgements and reminders. Issued text is frozen, all writes use
version checks and hold permission, and released holds retain read-only history.
The register does not deliver messages or verify a custodian's identity.

## Candidates, versions and optional local analysis

Deterministic source findings and comparisons use bounded SQL prefixes and current immutable artifact references. Near-duplicate candidates scan at most 100 items and return up to 20 matches; text comparison uses 20,000 characters/1,000 tokens per source. Candidate original verification is limited to 100 MB per source and 500 MB per request, with extracted artifacts up to 20 MB. Coverage reports show omitted, unverified and truncated material. These operations do not merge identities or apply factual/legal review decisions.

Historical extraction views verify the selected immutable artifact and original and label superseded versions. Reprocessing preserves those versions, while current candidates, citations, redaction approval and production use the current extraction. A source-integrity or version failure requires investigation or a fresh reviewed proposal, rather than alteration of stored bytes.

Keep local-model processing disabled until the configured runtime, model licence, host policy and matter scope are reviewed. Global `CASEQUARRY_AI_ENABLED=true` and a configured `CASEQUARRY_AI_MODEL` are insufficient alone: the matter lead must explicitly consent. The application accepts only a literal loopback endpoint, disables HTTP proxies and redirects, supplies no tools, and rejects remote/cloud model policies. Independently run Ollama with cloud features disabled and network controls appropriate to the host; a loopback address alone cannot attest to the runtime's external behavior. No model is installed or downloaded by the application. See [local-analysis safety](AI_SAFETY.md).

## Back up, restore and investigate failures

Follow [backup and recovery](BACKUP_RECOVERY.md) for database/object-store consistency, archive verification and an isolated restore drill. Protect the authentication/MFA encryption material required by that procedure. An uncoordinated copy of live `.data` is not a verified backup.

Inspect health, import errors, coverage, source hashes and audit-chain verification through the authorized UI/CLI/API. A hash-chain check detects inconsistency within the stored chain; it does not independently anchor a database against privileged host modification. Keep private diagnostics free of evidence bodies and credentials.

Source release archives contain application sources and required resources. They are separate from evidence exports, production packages and operational backups. Record the tested host/runtime, restored counts and hash results before relying on operational recovery.
