# Threat model

Protected assets are original evidence, derived text, credentials/sessions, case membership, review decisions, exports and audit records. Host administrators, storage administrators and the operator of an optional model runtime are privileged parties; application controls cannot make a compromised host safe.

| Threat | Required control and validation |
|---|---|
| Guessed case/item identifiers | Deny by default; tenant and case permission checks before search, counts, previews, citations, downloads, workers and exports |
| Stolen sessions / unsafe login | Password hashing, expiring sessions, CSRF protections for cookies, secure production cookies, MFA path and protected OS CLI keyring |
| Hostile MIME/HTML documents | Text-only or sanitized presentation; no script execution, macros or remote tracking-image fetches |
| Archive traversal / resource exhaustion | Refuse unsafe paths, symlinks, excessive nesting/expansion; bound request size, extraction and job concurrency |
| Original corruption | Preserve source bytes, SHA-256 on ingest and retrieval, explicit integrity failure, export refusal and verified recovery |
| Cross-case duplicate disclosure | Case/tenant scope dedup metadata and identifiers; no global hash existence oracle |
| Unsupported or interrupted extraction | Preserve original and source occurrence; durable job/checkpoint and visible partial/failed coverage |
| Prompt injection / provider leakage | Treat evidence as data; no model action tools, authorized retrieval, validated source citations, remote transmission off by default |
| Accidental privileged export | Role policy, explicit confirmation/reason, human review holdback and integrity checks; production redaction must fail closed |
| Database/audit tampering | Attributed append-only application events and chain verification; external anchors and independently protected storage remain separate assurance work |
| Supply-chain or public-repository leak | Pinned lockfiles, dependency inventory, secret/tooling ignores, source-only package review and no real client fixtures |
| Host loss / theft | Encrypted disk and independent encrypted backups, key separation and an actually executed restore drill |

Tests provide evidence for the particular paths they exercise. Unexecuted controls, incomplete adapters, production deployment and recovery/redaction assurances must remain visibly pending. The initial SQL search/queue backend has not proven multi-million-record capacity. Operators must assess their deployment, evidence handling duties and third-party dependency notices before genuine client use.
