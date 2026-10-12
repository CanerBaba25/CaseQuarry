# Offline development recovery

`scripts/backup.py` supports a stopped SQLite/API/worker installation and a new isolated restore directory. It does not support online backup coordination or PostgreSQL. Keep the passphrase outside the backup/evidence store and protect the operator's temporary directory and disk; temporary plaintext is required while taking/verifying a snapshot.

```sh
uv run python scripts/backup.py create --db .data/casequarry.db --storage .data/storage --output .data/backups/evaluation.cqbackup --confirm-services-stopped
uv run python scripts/backup.py restore-verify --backup .data/backups/evaluation.cqbackup --target .data/isolated-restore
```

The passphrase is requested with hidden input and is never printed. For private automation it may be supplied through the process environment `CASEQUARRY_BACKUP_PASSPHRASE`, not command arguments or committed files.

Backups use AES-256-GCM with scrypt derivation and random salt/nonce. SQLite snapshot integrity is checked; a streaming archive records every data file's SHA-256 and size. Restore authenticates the encrypted archive before extracting, refuses traversal/symlinks/nonregular entries, enforces a byte quota, verifies every manifest record and SQLite integrity, and publishes the restore only into a previously nonexistent directory. Existing application data is never overwritten.

Local recovery tests cover round-trip bytes/database, wrong passwords, modified ciphertext, unsafe paths, quotas and overwrite refusal. Test files are private QA assets excluded from the public source package. This establishes the tested offline utility scope; it is not a verified live-service disaster recovery procedure. Before operational recovery, review configuration, invalidate old sessions and test a complete isolated application startup and permission/evidence workflow. Protect host access, encrypted disks and independently stored backup keys separately.
