# Database and evidence recovery

PostgreSQL is the normal database. A recoverable firm backup includes its database, immutable storage directory, private server `.env` and provider encryption key. If export signing is configured, also preserve the separately stored Ed25519 private PEM: `.env` contains only its path. A database dump cannot recover missing originals, and encrypted credential rows cannot recover keys after the master key is lost.

## PostgreSQL

This release uses PostgreSQL `pg_dump`/`pg_restore` with coordinated manual service stopping; it does not implement automated online point-in-time backup. Stop API/worker before capturing the database and corresponding storage. Keep PostgreSQL running for the dump. Set `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and an owner-protected `PGPASSFILE` privately; credentials must not appear in arguments:

```sh
pg_dump --format=custom --no-owner --no-acl --file=firm.dump
```

Copy immutable storage and private configuration into encrypted, access-controlled backup storage. Record hashes/schema revision, retain an off-host copy and protect backup credentials separately. Keep the provider master key recoverable by authorized operators; do not distribute it to desktop clients.

Keep export-signing private keys outside evidence storage and restrict their backup
to authorized operators. Retain historical trusted public keys and key identifiers
separately so recipients can verify older signed ZIPs after rotation. Restoring a
backup does not create or rotate keys. See [signed-package recovery](SIGNED_EXPORTS.md).

Restore into a new isolated database and separate storage:

```sh
pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname=NEW_EMPTY_DATABASE firm.dump
```

Set the new private connection/storage configuration and run `python -m casequarry.database status`. A package supporting the dump's revision must validate it before forward upgrades. Verify original hashes, audit chains, users/membership, representative searches/reviews and isolated startup. Do not overwrite live data to rehearse recovery. Invalidate copied sessions before operational cutover and restore TLS/CA material through the operator's certificate procedure.

[pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html) takes a consistent database snapshot; it does not coordinate the separate evidence store. [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html) handles the custom dump. Continuous archiving and point-in-time recovery are operator-managed PostgreSQL capabilities, not features supplied by this release.

## Legacy SQLite

`scripts/backup.py` retains its tested stopped-SQLite scope. It authenticates a streaming storage archive with AES-256-GCM/scrypt and refuses overwrite, unsafe paths/symlinks, wrong passwords, quotas and manifest/hash failures. Temporary plaintext needs protected disk. It does not generate a PostgreSQL backup.

```sh
uv run python scripts/backup.py create --db PATH_TO_LEGACY.sqlite --storage EXISTING_STORAGE --output NEW_BACKUP.cqbackup --confirm-services-stopped
uv run python scripts/backup.py restore-verify --backup NEW_BACKUP.cqbackup --target NEW_ISOLATED_DIRECTORY
```

The passphrase uses hidden input or process `CASEQUARRY_BACKUP_PASSPHRASE`, never plaintext arguments. Retain the encrypted backup and original SQLite file until restore checks pass.

For permanent cutover, use the [guarded SQLite transfer](SERVER_INSTALL.md#existing-sqlite-installations) with stopped API/worker, a known schema, a new snapshot and an empty PostgreSQL target. It preserves source/storage, copies rows transactionally and verifies counts, original hashes and audit chains. Change the private URL only after verification. Unknown schemas and populated targets are rejected.

Local QA covers SQLite backup safety and real PostgreSQL migrations/imports/concurrency; those files remain excluded from GitHub. A firm still needs a rehearsed complete restore on its own host, storage and access configuration.
