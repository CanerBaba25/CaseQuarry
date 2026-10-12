# Data handling

Evidence stays on the configured private server by default. Imported originals are preserved; extracted text and preview metadata are derivatives. Content hashes verify bytes, not the truth, authenticity, admissibility or lawful acquisition of a document.

Core import/search/review/export work without a model. Remote AI and outbound telemetry are disabled by default. Installing a local model is optional and does not grant it evidence access automatically. Retrieved document instructions are untrusted data, never authorization to perform actions or disclose another matter.

Local storage is not automatically disk encryption. Use an encrypted filesystem and backups, keep keys outside the evidence store, restrict host access and complete restore verification before handling client material. SQLite and Docker volumes persist data until deliberately removed; `docker compose down` keeps named volumes, while `down --volumes` destroys them and is not a routine shutdown command.

Keep uploads, extracted content, secrets and diagnostics out of public issues, logs and source releases. Only synthetic fixtures belong in tests or screenshots. `.env`, `.data`, private instructions, tooling graphs/caches and release archives are ignored by Git; source packages also reject tracked private artifacts.

CaseQuarry is a technical review aid, not legal advice, automatic privilege determination, an admissibility guarantee or a compliance certification. The initial release is suitable for synthetic evaluation while launch gates remain open.
