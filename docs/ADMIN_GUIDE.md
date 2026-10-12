# Administrator guide

Start with [the platform installation guide](INSTALL_WINDOWS.md), a private encrypted host and a synthetic evaluation corpus. First-run setup requires the generated one-time local token and a new administrator password. Keep `.env` owner-restricted and do not commit it.

Administrator configuration does not imply unrestricted matter-content access. Grant users only the cases/roles their work requires and test access boundaries using separate accounts. Worker jobs must recheck the submitting identity's current case access. Disable or remove access through audited product routes, not by changing source evidence files.

Development SQLite is the verified local path. The Compose configuration selects PostgreSQL and a separate durable SQL worker; container acceptance remains pending until executed on a Docker host. No OpenSearch, RabbitMQ or external connector is silently required by the current release.

Keep AI disabled until you have reviewed the configured local endpoint, scope, model licence and hardware. Remote evidence transmission is disabled. Never treat extracted or suggested privilege as a final legal determination.

Before operational use, verify original hashes, export policies, independent backup/restore, production TLS/cookies, filesystem encryption, access revocation, dependency notices and legal/practitioner approval. A copy of `.data` made while jobs are writing is not a verified backup strategy. Do not delete data or Docker volumes as a troubleshooting shortcut.

Use the implemented CLI/API health and job status routes to inspect failures. Private diagnostics must avoid evidence bodies, secrets and prompts. Source release ZIPs use reviewed committed source; they are separate from evidence exports and backups.
