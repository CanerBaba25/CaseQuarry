# Feature comparison

Reviewed on 14 October 2026 UTC using the five projects' repository READMEs,
documentation, licence files and selected implementation paths at the revisions below.
The referenced applications were not independently installed, executed or tested.
Demo availability, format counts and benchmark descriptions do not establish
production capacity or suitability for a particular matter.

## Existing CaseQuarry coverage

CaseQuarry already provides a shared PostgreSQL firm server with browser and native
desktop clients, matter permissions, custodians, preservation holds, audit chains,
immutable extraction versions and hash verification. Its bounded ingestion covers
EML, MBOX, MSG, common documents, images and ZIP containers, with OCR and durable
jobs. Read-only TLS IMAP acquisition is available through the CLI.

Review includes Boolean and field search, saved scopes, assignments, tags, notes,
email threads, communication maps, timelines and candidate comparisons. Disclosure
supports reviewed native exports and separate approved redacted Bates productions.
Optional local or approved cloud analysis uses source quotations, verified
citations and human review. See the [product overview](../README.md),
[adapter boundaries](ADAPTERS.md), [reviewer guide](REVIEWER_GUIDE.md) and
[administration guide](ADMIN_GUIDE.md).

Version 0.6.0 adds task priorities and richer personal-worklist triage,
plus web and native interface localization for English, Russian, French, Spanish,
German, Turkish, Greek, Italian, Portuguese, Ukrainian, Simplified Chinese,
Traditional Chinese and Hindi (`en`, `ru`, `fr`, `es`, `de`, `tr`, `el`, `it`, `pt`,
`uk`, `zh-Hans`, `zh-Hant`, `hi`). Interface translation does not establish OCR, search-analysis or model
quality in those languages. Version 0.7.0 adds Kimi alongside the other four optional cloud providers.

PST/OST import, OAuth mail connectors, media transcription and large-scale ranked
search remain unfinished. Production capacity and the two-million-email target
remain unvalidated. Unsigned export manifests use SHA-256 verification without an
independent timestamp.

## Additions in CaseQuarry 0.8.0

Two gaps from the source comparison are implemented independently:

- **Optional signed ZIP packages**, informed by Mike's signed JSON-manifest workflow.
  A dedicated operator-managed Ed25519 key signs the exact manifest bytes. The
  manifest inventories every data member, including production images and load
  files. Offline CLI verification requires an independently trusted public key and
  checks the signature, complete inventory, byte lengths and hashes. Unconfigured
  servers retain unsigned exports; an invalid configured key cannot silently
  downgrade a package. See [signed packages](SIGNED_EXPORTS.md).
- **Custodian hold-notice register**, informed by eDiscovery's notice records.
  Staff record draft notices, issuance, acknowledgement and reminders with version
  checks and an audit history. Issued text is frozen; account-local dates identify
  overdue reminders. These are manual records, without automatic email delivery,
  public acknowledgement links or verified custodian identity. Releasing a hold
  retains the notice history and stops further notice changes.

The existing preservation, privilege, independent approval and matter-permission
rules still apply. Signing authenticates a manifest relative to a trusted key; it
does not independently timestamp it, certify collection completeness or prove
chain of custody. Notices do not expand or release the underlying legal hold.

## Referenced projects and inspected revisions

| Project                                                     | Revision inspected                                                                                         | Source-supported differences                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [FreeEed](https://github.com/shmsoft/FreeEed)               | [`d268fac3`](https://github.com/shmsoft/FreeEed/commit/d268fac3c59beb91b3d9d77d7c386657d149ac4d)           | [PST traversal](https://github.com/shmsoft/FreeEed/blob/d268fac3c59beb91b3d9d77d7c386657d149ac4d/freeeed-processing/src/main/java/org/freeeed/main/PstProcessor.java#L185) invokes a separate parser. Its README advertises broader Tika formats and transcription; the inspected transcription path did not establish end-to-end ingestion.                                                                                                                                                                                                                                               |
| [OpenArchiver](https://github.com/kayoom/OpenArchiver)      | [`f01d1b17`](https://github.com/kayoom/OpenArchiver/commit/f01d1b176cc5f988a80965051f557b382d364ca7)       | [Scheduled incremental collection](https://github.com/kayoom/OpenArchiver/blob/f01d1b176cc5f988a80965051f557b382d364ca7/packages/backend/src/jobs/processors/continuous-sync.processor.ts), [mailbox checkpoints](https://github.com/kayoom/OpenArchiver/blob/f01d1b176cc5f988a80965051f557b382d364ca7/packages/backend/src/services/ingestion-connectors/ImapConnector.ts#L170), provider delta cursors and S3 storage extend explicit one-time acquisition.                                                                                                                              |
| [eDiscovery](https://github.com/JeremyFlorence/ediscovery)  | [`3cb43be9`](https://github.com/JeremyFlorence/ediscovery/commit/3cb43be95100c48ef1f1647296b151b689471f76) | [Per-custodian hold notices](https://github.com/JeremyFlorence/ediscovery/blob/3cb43be95100c48ef1f1647296b151b689471f76/holds/models.py#L59) and acknowledgement/reminder records extend basic hold activation. [Views](https://github.com/JeremyFlorence/ediscovery/blob/3cb43be95100c48ef1f1647296b151b689471f76/holds/views.py#L81) record issuance/reminders; actual email delivery is left unimplemented.                                                                                                                                                                             |
| [Mike](https://github.com/open-legal-products/mike)         | [`08e6c649`](https://github.com/open-legal-products/mike/commit/08e6c6499b854aabb29a39eecf65a509c7590c53)  | [Signed JSON manifests](https://github.com/open-legal-products/mike/blob/08e6c6499b854aabb29a39eecf65a509c7590c53/backend/src/lib/manifestSigning.ts#L60), [tabular question workflows](https://github.com/open-legal-products/mike/blob/08e6c6499b854aabb29a39eecf65a509c7590c53/frontend/src/app/components/workflows/WFEditColumnModal.tsx#L93), research and drafting offer distinct additions. Its Word integration is beta; signed JSON does not establish generic ZIP sealing.                                                                                                      |
| [LegalMemory](https://github.com/eigenweltlabs/LegalMemory) | [`8ac42f04`](https://github.com/eigenweltlabs/LegalMemory/commit/8ac42f04fbbf23bd1a486390308c038e0908df46) | [Mirrored ACL predicates](https://github.com/eigenweltlabs/LegalMemory/blob/8ac42f04fbbf23bd1a486390308c038e0908df46/src/knowledge_index/permissions.py#L144), [permission-scoped ranking](https://github.com/eigenweltlabs/LegalMemory/blob/8ac42f04fbbf23bd1a486390308c038e0908df46/src/knowledge_index/retrieval.py#L2088), source synchronization and [Word revision/comment extraction](https://github.com/eigenweltlabs/LegalMemory/blob/8ac42f04fbbf23bd1a486390308c038e0908df46/src/knowledge_index/pipeline/converters.py#L100) extend matter permissions and extraction history. |

The requested OpenArchiver fork points to another organization in its installation
instructions; this comparison concerns the exact requested snapshot. Its legal
holds are marked TBD. Its inspected storage code enables encryption only when a
key is configured, so the README's blanket encryption wording is not adopted.
FreeEed marks responsiveness/privilege/smoking-gun analysis as under development.
LegalMemory's inspected document-ranking function fuses three document legs, with
decision search separately available; the README's four-leg wording is not repeated
as a verified description of that function. No advertised benchmark is imported.

## Recommended next work

These remain proposals, not delivered capabilities or release commitments:

| Priority | Addition                                              | Bounded first delivery                                                                                                                                                                                                                                       |
| -------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1        | Incremental read-only mailbox collection              | Extend the existing IMAPS CLI with durable host/mailbox/UIDVALIDITY/UID checkpoints. Advance only after preservation, report partial coverage and require reconciliation after UIDVALIDITY changes. Scheduling and provider OAuth follow separately.         |
| 2        | Isolated PST adapter                                  | Detect an independently installed parser, preserve the container and retain stable message/folder provenance. Bound bytes, time and family expansion; report unsupported Outlook objects. OST is a separate format.                                          |
| 3        | Structured review-question matrix                     | Reusable typed questions over fixed review scopes, with human-entered answers and immutable source anchors. Optional model suggestions remain separate from responsiveness and privilege decisions.                                                          |
| 4        | Word tracked revisions and comments                   | Extract bounded OOXML changes into a separate provenance artifact. Keep visible text, deleted text, source author/date claims and human conclusions distinct.                                                                                                |
| 5        | Permission-aware source synchronization and retrieval | Start one read-only source with ACL snapshots, resumable scans and fail-closed scope checks before ranking. Record deletion observations without deleting preserved or held evidence. Benchmark retrieval quality as well as speed.                          |
| 6        | Encrypted evidence storage and S3                     | Stage storage changes independently. Preserve authenticated reads, write-once objects, plaintext content hashes, key rotation, temporary-file limits and verified recovery. Current provider-key and backup encryption do not encrypt live evidence objects. |

## Reuse boundaries

The additions are independently authored. No referenced repository implementation,
template, model or proprietary driver is incorporated into CaseQuarry.

- FreeEed's [Apache-2.0 root licence](https://github.com/shmsoft/FreeEed/blob/d268fac3c59beb91b3d9d77d7c386657d149ac4d/LICENSE) includes a separate proprietary JPST-driver note; its EULA distinguishes optional commercial components.
- The inspected [OpenArchiver](https://github.com/kayoom/OpenArchiver/blob/f01d1b176cc5f988a80965051f557b382d364ca7/LICENSE), [Mike](https://github.com/open-legal-products/mike/blob/08e6c6499b854aabb29a39eecf65a509c7590c53/LICENSE) and [LegalMemory](https://github.com/eigenweltlabs/LegalMemory/blob/8ac42f04fbbf23bd1a486390308c038e0908df46/LICENSE) revisions use AGPL-3.0, with component-specific notices where supplied.
- No licence grant was found in the inspected eDiscovery tree or README. Public visibility alone does not supply reuse permission.

Any future dependency or source adoption needs review of that exact component and
revision. This feature comparison supplies no licence-compatibility clearance.
