# Feature comparison

Reviewed on 13 October 2026 using the five projects' repository READMEs,
documentation and licence files. Their capabilities below are documented by the
projects, not independently installed, executed or tested for this comparison.
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
quality in those languages.

PST/OST import, OAuth mail connectors, media transcription and large-scale ranked
search remain unfinished. Production capacity and the two-million-email target
remain unvalidated. Current export manifests use SHA-256 verification without a
digital signature or independent timestamp.

## Referenced projects

| Project                                                                            | Documented capabilities and useful differences                                                                                                                                                                                                                                                                   | Status and licence boundaries                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [FreeEed](https://github.com/shmsoft/FreeEed#capabilities)                         | PST processing, OCR, document review, PDF imaging, audio/video transcription and a claimed 1,400+ formats through Apache Tika. PST and transcription extend CaseQuarry's current adapter coverage.                                                                                                               | Its README explicitly marks AI responsiveness, privilege and smoking-gun analysis as under development. The [root LICENSE](https://github.com/shmsoft/FreeEed/blob/main/LICENSE) is Apache-2.0 and includes a proprietary JPST-driver note distinguishing evaluation from production licensing. Its [EULA](https://github.com/shmsoft/FreeEed/blob/main/EULA.txt) distinguishes open-source components from optional commercial features. |
| [OpenArchiver](https://github.com/kayoom/OpenArchiver#-key-features)               | Google Workspace, Microsoft 365 and IMAP synchronization; PST, EML and MBOX ingestion; local/S3-compatible storage; email thread context and integrity reports. OAuth synchronization is the main difference from CaseQuarry's existing read-only IMAP acquisition.                                              | Features and a live demo are advertised in the README; legal holds are explicitly marked TBD. The requested kayoom repository links another organization as its installation upstream. The exact [root licence](https://github.com/kayoom/OpenArchiver/blob/main/LICENSE) is GNU AGPL v3.                                                                                                                                                 |
| [JeremyFlorence/ediscovery](https://github.com/JeremyFlorence/ediscovery#features) | A Django review application with custodian hold notices, acknowledgement links, reminder tracking and acknowledgement-rate reporting, alongside review coding and Bates productions. The notice workflow extends basic preservation-hold tracking.                                                               | The README describes a runnable application and 26 tests; those tests were not executed for this comparison. No root LICENSE file or README licence declaration was found at review. Public source visibility does not establish permission to reuse it.                                                                                                                                                                                  |
| [Mike](https://github.com/open-legal-products/mike#features)                       | Reusable assistant and tabular-review workflows, CourtListener research, Word integration and local Ollama support. Its [export guide](https://github.com/open-legal-products/mike/blob/main/docs/tamper-evident-exports.md) documents optional Ed25519 manifest signatures and trusted public-key distribution. | The Word add-in is explicitly beta. CaseQuarry already has optional local analysis and verified citations; those alone are not gaps. Mike's [root licence](https://github.com/open-legal-products/mike/blob/main/LICENSE) is GNU AGPL v3.                                                                                                                                                                                                 |
| [LegalMemory](https://github.com/eigenweltlabs/LegalMemory#highlights)             | Read-only document-source synchronization with mirrored ACLs, permission filtering before ranking, hybrid retrieval, document-version collapse and identity-bound MCP access. These offer a longer-term reference for external document estates.                                                                 | Its README describes a live demo and a retrieval benchmark gate; neither establishes independently validated production capacity here. Its [licence](https://github.com/eigenweltlabs/LegalMemory/blob/main/LICENSE) is GNU AGPL v3, with component notices and a commercial alternative described in the README.                                                                                                                         |

## Recommended additions

These are proposed gaps, not delivered capabilities or release commitments. Scope
estimates are relative and require verification against the current implementation.

| Priority | Addition                                                  | Bounded scope and practical risks                                                                                                                                                                                                                                                                     |
| -------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | Optional signed export manifests                          | Small to medium. Extend existing exports and CLI verification with a versioned signature format, dedicated operator-managed signing key and key identifier. Verify against an explicitly trusted public key. Key custody, rotation and public-key distribution need a documented operating procedure. |
| 2        | Custodian hold-notice register                            | Medium. Extend existing holds with versioned notice records, acknowledgement history and reminder dates. First verify which fields are already implemented. A manually recorded acknowledgement must be labelled as such; public acknowledgement links require separate token and identity design.    |
| 3        | Saved structured review templates                         | Medium to large. Add reusable question/column definitions over bounded evidence scopes, retaining source citations, coverage and separate human decisions. Avoid treating generated values as authoritative review coding.                                                                            |
| 4        | OAuth synchronization and PST acquisition                 | Large; deliver as separate adapters. Start with one provider or container format, durable checkpoints and explicit coverage limits. Handle token expiry, provider quotas, duplicate occurrences, parser isolation and provenance before expanding coverage.                                           |
| 5        | Permission-aware DMS synchronization and hybrid retrieval | Large; stage independently from core review. Preserve source ACLs, fail closed on unknown access, reconcile deletion observations and benchmark scoped retrieval. Do not inherit another project's capacity claims.                                                                                   |

The most bounded next addition is optional signed export manifests, informed by
Mike's documented workflow. Preserve unsigned operation when no signing key is
configured. Verification should fail for modified manifests, changed package files
and an incorrect trusted key, while supporting historical signing keys after
rotation. A signature authenticates a manifest relative to the trusted key; it does
not provide an independent timestamp or prove chain of custody. This feature is
proposed and has not been implemented by this comparison.

## Reuse boundaries

These projects are references for independent feature design. No referenced
repository code is included by this comparison. AGPL-covered code has copyleft
conditions, including conditions for modified software used over a network;
importing or adapting it requires a separate licence-compatibility review.
Permissively licensed components also retain their applicable notices and terms.
FreeEed's component-specific and distribution terms require separate attention,
and the absence of a licence in the reviewed ediscovery repository supplies no
reuse permission. Verify the exact revision and component licences before any
dependency decision. This comparison is not legal clearance.
