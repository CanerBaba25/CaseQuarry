# Reviewer guide

This guide describes the implemented 0.8 workflows. Start with a synthetic evaluation matter. Your matter role controls the available actions; being a firm administrator does not grant access to every matter.

## Find and inspect evidence

1. Open an authorized matter and check its import coverage. Preserved originals, searchable items, partial extractions, failures and quarantine are distinct states. A partial or unsupported item does not establish that the original lacks relevant content.
2. Use the explorer to search words, phrases, Boolean expressions and supported metadata fields. Apply filters, sort and grouping before paging. Group totals describe the authorized matching set; the visible page contains a bounded subset. Save a search or create a review set when you need a reproducible scope.
3. Open an evidence item. Compare extracted text with its source, attachment family, source occurrence, raw and normalized dates, processing warnings and SHA-256. HTML is presented as safe text; remote tracking assets and scripts are not rendered.
4. Inspect OCR warnings and page-level confidence when present. OCR confidence is an engine estimate, and recognized text needs human verification. Use the authenticated PDF raster preview to inspect a visible page without executing the original PDF in the browser.

Original downloads preserve their bytes. Extracted text, OCR, redacted previews and production documents are separate derivatives. Dates without a reliable timezone must retain that uncertainty.

Use **Previous item** and **Next item** in the inspector to move through the current
result page in its displayed order. The buttons stop at page boundaries and while
tags or a note have unsaved changes. Save or clear those drafts before moving.
**Copy source link** points to that span in its exact extraction version, which opens
as a read-only view. Sharing a link does not grant access to the matter. Evidence rows
refresh after another workstation saves a review; a version conflict still requires
you to inspect the latest decision before saving.

## Plan and track tasks

The dashboard's **My work** lists your open and in-progress assignments across
accessible active matters. Filter by status and deadline; counts cover the authorized
scope rather than just the current page. Click a task title to inspect its full
description and, with review permission, edit its title, description, status,
assignee and due date. Matter task lists use the same editor.

Task saves carry the version you opened. If another person changes the task first,
your draft stays available while you compare the latest record. Reload or explicitly
rebase the fields you changed, then save again; the app does not silently retry the
conflicting edit. Deadline and assignment changes can restart a paged worklist to
avoid skipping tasks. Choose your account timezone in Settings; entered due dates
remain calendar dates. These plans are entered by the team and are not calculated
court deadlines. See the [task API and conflict behavior](TASK_API.md).

## Record review and use assignments

Record responsiveness, privilege flags, tags, notes and bookmarks in the evidence inspector. Only a matter lead or attorney can change final privilege determinations. A suspected flag is a review concern rather than a final conclusion. On a review-version conflict, reload the item and compare the other reviewer's decision before saving again.

The **Review queue** contains assignments with a fixed evidence snapshot:

1. A matter lead or review manager creates an assignment from explicit evidence IDs or a review set, with a title and reason. Each assignment contains 1–500 items. Later changes to that review set do not expand the assignment.
2. The manager may choose an active matter member with review permission or leave the assignment unassigned. An item cannot belong to two active assignments.
3. Claim an unassigned assignment to become its reviewer. The assignment version prevents two reviewers from claiming the same queue entry. Review its paginated items normally.
4. Complete the assignment after every item is `responsive` or `non_responsive`. `unreviewed` and `needs_review` items block completion. Completion closes the allocation; it does not clear suspected or confirmed privilege.
5. Release an assignment when another reviewer should claim it. Only its assignee or a matter manager may release or complete it; cancellation requires a manager. A released assignment retains its fixed scope and remains an active allocation until completed or cancelled.

Claiming or releasing changes the evidence assignment and review version. Finish assignment changes before requesting a redaction or production approval, because those approvals capture the review version.

## Inspect candidates and extraction versions

Use source findings and comparison as investigation aids:

| Operation            | Actual scope and interpretation                                                                                                                                                                                                                                  |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Near duplicates      | Word-trigram similarity over the first 20,000 characters and at most 5,000 words. The candidate pool is ID-ordered and capped at 100 items; up to 20 verified matches are returned. Exact original duplicates are excluded from this candidate search.           |
| Extracted candidates | Regex patterns for email addresses, dates, currency amounts and explicitly labeled invoice numbers. Returned findings cite exact current artifact spans; at most 200 findings are considered. Names, roles, obligations and company identities are not inferred. |
| Document comparison  | Exact extracted-text differences with passages and provenance from both sources. Each input is bounded to 20,000 characters and 1,000 tokens; up to 200 diff segments are returned.                                                                              |

Read each operation's coverage and limits. Truncated text or candidate coverage means the result does not describe the complete corpus or document. Similarity, a date pattern or a changed passage does not establish identity, authenticity, event timing or contradiction. These operations do not merge identities, delete duplicates or apply review decisions.

The inspector can list immutable extraction versions and display a historical version. A superseded extraction is labeled explicitly and retains its original artifact hash and spans. Current search, candidates and productions use the latest version. After an authorized import retry, inspect changes before relying on an earlier review; old human reviews remain recorded. Source or artifact integrity failure blocks a verified view.

## Map and review issues

Create an issue and link evidence as `supports`, `contradicts` or `unclear`, with an optional explanatory note. Links are restricted to the current matter. A matter lead or attorney may mark an issue `reviewed` only after it has linked evidence. Reviewers may flag `disputed` or `needs_review`.

Issue review records capture the linked evidence and its extraction/review state. A stale indicator means the links or underlying state changed after that review; inspect the issue again before relying on its earlier conclusion. Issue-review versions prevent silent overwrite by another reviewer.

## Prepare and approve redactions

Create a request in **Productions**, identifying the source evidence and the reason:

- **PDF:** use the authenticated page preview and select normalized rectangles. Coordinates use the top-left of the visible page. Requests support up to 200 regions, PDF originals up to 50 MB and documents up to 50 pages; rendering is bounded to 40 million pixels per document.
- **Text:** select non-overlapping character ranges in the current immutable extracted text. Submit its current artifact version with those offsets. Text redaction produces UTF-8 text, preserving the source original and excluding its native layout, headers or attachments that were not part of that extraction.

The worker creates a separate derivative and moves it to `ready_for_review`. A PDF derivative is rebuilt from lossless page pixels: selected regions are opaque black, and original text layers, metadata, annotations, attachments and other source objects are not copied. Text derivatives replace only the selected ranges with `[REDACTED]`.

A **different** current matter lead or attorney must inspect the sanitized preview and approve it with confirmation and a reason. The requester cannot approve their own redaction. Reject an incorrect ready preview and submit a new request. Approval records do not replace the evidence's human responsiveness or privilege review.

Inspect every selected page or passage, including repeated sensitive text elsewhere. Only the chosen rectangles or ranges are removed; the application does not claim that all sensitive information was discovered. The preview is an internal authorized review download, not an approved external production.

## Produce a reviewed package

1. Select explicit evidence IDs, a review set or a query scope. A proposal contains at most 200 evidence items. Confirm its purpose, choose an uppercase Bates prefix beginning with a letter (up to 16 characters), and attach approved redactions to the matching items.
2. Every selected item needs completed human responsiveness review and privilege status `none` or `cleared`. Suspected/confirmed privilege and quarantined items block production. Identical original occurrences cannot be included with different redactions or with an unredacted duplicate beside a redacted occurrence.
3. A different current matter lead or attorney approves the proposal with a reason and confirmation. They may reject an incorrect proposal. Approval snapshots the reviewed source and redaction state; subsequent changes invalidate the production.
4. Wait for completion. Bates controls use a persistent eight-digit registry per matter and prefix. Numbers reserved for failed attempts are not recycled; recovering the same leased job reuses its existing range. Source content is never stamped or changed.
5. Download the completed package and inspect its manifest, document hashes, boundaries and load-file mappings before recipient delivery. The package and every source are rechecked at download, including current requester and approver permissions.

The production is **derived only**: flattened PDFs with a new Bates footer or UTF-8 text documents with a Bates control. It never bundles an unredacted original native beside a redacted derivative. Only selected evidence IDs are delivered; family relationships are recorded by ID, and attachments outside that scope are omitted. Source titles, filenames, paths, participants, internal reasons and query text are omitted from the recipient package.

The ZIP includes `manifest.json`, document-level `loadfile.csv` and `loadfile.dat`, and page-level `images.opt` referencing single-page flattened PDFs. The explicit DAT profile uses UTF-8 with a BOM, U+0014 columns, U+00FE quoted fields and CRLF rows. OPT uses seven ASCII comma-separated columns with relative Windows paths; text-only documents have a control number and no OPT image entry. This profile has internal round-trip fixtures, but no recipient platform import has been executed. Configure and test the recipient's field, delimiter and image settings before delivery.

Production limits also include 60 million rendered pixels across a job, 250 MB of produced document/image content, and complete indexed text up to 2 MB per text derivative. Split larger scopes. Hash manifests provide application SHA-256 verification, without a digital signature or independent time anchor.

An active legal hold preserves originals and blocks archival release paths that would violate preservation. It does not authorize disclosure or override privilege holdback. Reviewed native ZIP exports are a separate workflow; they include original bytes and require review of embedded descendants. Do not use a native export to deliver a redacted production.

When the server is configured for signing, completed ZIP exports and productions
show their signing key identifier. Give recipients an independently trusted public
key and use [offline signed-package verification](SIGNED_EXPORTS.md); CSV/JSON and
unconfigured ZIP exports remain unsigned. A signature does not replace source,
redaction or privilege review.

Matter leads and attorneys can maintain [custodian hold notices](HOLD_NOTICES.md)
through **View notices** on a preservation hold. The register records manual
issuance, reminders and acknowledgements. Issued text is immutable and a released
hold's history remains read-only. It does not send messages or verify recipients.

## Optional local source-cited analysis

Core review works while the local model is disabled. If an administrator configures it and a matter lead explicitly consents, analysis returns extractive source quotations with artifact citations and coverage. Unsupported, cross-matter or fabricated quotations are rejected. Inspect the cited context before accepting or rejecting a finding; that action changes only the finding's review state, not legal evidence decisions. See [local-model safety](AI_SAFETY.md).

## Account and recovery

Use account security to enroll an authenticator, change your password and inspect or revoke your active sessions. Password changes require your current password and an authenticator code when MFA is enabled; other sessions are revoked. Keep recovery codes private.

If a job or download is blocked, read its actual error and processing coverage. Recheck source hashes, review status, permissions and supported limits before submitting a new proposal. An integrity failure is a reason to investigate preservation, not to change a stored original to make the error disappear.

CaseQuarry assists review. It does not decide privilege or admissibility, establish document authenticity from a comparison score, or prove completeness of a collection.
