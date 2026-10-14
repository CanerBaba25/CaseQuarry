# Evidence integrity

The import pipeline hashes original bytes with SHA-256 and stores source occurrences independently from physical object deduplication. Each occurrence retains its collection/source context. Attachments are linked to their parent email and have their own originals and hashes.

Processing creates extracted text and derivative metadata; it does not rewrite preserved originals. Unsupported, locked and failed files remain inventory records with actionable states. Searchable and preserved counts are different and must be reported separately.

Use `casequarry evidence verify ITEM_ID --case CASE_ID` for a fresh original hash check. Authorized original download and export must refuse detected integrity failure. Export packages carry a hash manifest; verify the recorded SHA-256 against downloaded original bytes before sharing or archiving. CSV/JSON metadata exports and ZIPs created without a configured signing key remain unsigned.

Version 0.8.0 optionally signs native export and derived production ZIPs with Ed25519. Verify a received signed package offline with `cq evidence verify-package --path received.zip --trusted-public-key trusted.pem`. Obtain that public key through an independently trusted process; a key supplied only beside an unknown ZIP does not establish identity. Verification checks the exact signed v2 manifest and every listed data member's bytes, size and SHA-256 without extracting the archive. See [signed packages, trust and rotation](SIGNED_EXPORTS.md).

Application controls and audit chains detect defined inconsistencies; a host administrator can still modify data and the database or misuse a signing key accessible to that account. The optional signature proves control of the independently trusted key for the signed manifest; it provides no independent timestamp, collection-completeness proof or custodian identity verification. Independently protected audit anchors and object-lock storage remain unimplemented. No legal or forensic certification is claimed.
