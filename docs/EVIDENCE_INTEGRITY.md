# Evidence integrity

The import pipeline hashes original bytes with SHA-256 and stores source occurrences independently from physical object deduplication. Each occurrence retains its collection/source context. Attachments are linked to their parent email and have their own originals and hashes.

Processing creates extracted text and derivative metadata; it does not rewrite preserved originals. Unsupported, locked and failed files remain inventory records with actionable states. Searchable and preserved counts are different and must be reported separately.

Use `casequarry evidence verify ITEM_ID --case CASE_ID` for a fresh original hash check. Authorized original download and export must refuse detected integrity failure. Export packages carry a hash manifest; verify the recorded SHA-256 against downloaded original bytes before sharing or archiving.

Synthetic fixture `golden.json` lists expected query counts and document hashes. `email-hashes.jsonl` streams original EML fixture hashes; MBOX-derived message bytes can differ through format framing and have their own preserved hash. Import the MBOX or its example EML copies, not both, when validating the listed occurrence total.

Application controls and audit chains detect defined inconsistencies; a host administrator can still modify both data and database. Independent anchors, object-lock storage and externally protected signatures are future assurance mechanisms. No legal or forensic certification is claimed.
