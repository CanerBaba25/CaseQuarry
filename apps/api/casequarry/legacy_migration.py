"""Copy a verified legacy SQLite snapshot into an empty PostgreSQL instance."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, MetaData, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import audit
from .config import Settings
from .database import Database, SchemaMismatch, known_schemas, schema_differences
from .models import AuditHead, Base, Original
from .storage import Storage, file_hash


def transfer_sqlite(source_path: Path, storage_root: Path, backup_path: Path, settings: Settings):
    """Leave the source untouched; lock and atomically populate an empty target."""
    source_path, backup_path = source_path.resolve(), backup_path.resolve()
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        raise SchemaMismatch("TARGET_POSTGRES_REQUIRED", "The migration target must be PostgreSQL.")
    if not source_path.is_file() or source_path.is_symlink() or source_path == backup_path or backup_path.exists():
        raise SchemaMismatch("SOURCE_BACKUP_INVALID", "Choose an existing SQLite file and a new separate backup path.")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(backup_path) as snapshot:
        original.backup(snapshot)
    source = create_engine("sqlite:///" + backup_path.as_posix())
    target = Database(settings)
    try:
        with source.connect() as read:
            revisions = read.execute(text("SELECT version_num FROM alembic_version")).scalars().all() if "alembic_version" in inspect(read).get_table_names() else []
            candidates = revisions or sorted(known_schemas(), reverse=True)
            matched = [revision for revision in candidates if revision in known_schemas() and not schema_differences(read, revision)]
            if len(revisions) > 1 or not matched:
                raise SchemaMismatch("LEGACY_SCHEMA_UNKNOWN", "The SQLite snapshot must exactly match a known static revision; the source was not changed.")
            revision = matched[0]
            metadata = MetaData()
            metadata.reflect(read, only=list(known_schemas()[revision]))
            storage = Storage(storage_root)
            originals_checked = 0
            table = metadata.tables["original_objects"]
            for row in read.execute(select(table)).mappings().yield_per(500):
                if file_hash(storage.path(row["storage_key"])) != (row["sha256"], row["byte_size"]):
                    raise SchemaMismatch("LEGACY_ORIGINAL_INTEGRITY", "A preserved original failed its actual size/hash check. Target data was not published.")
                originals_checked += 1
            target.migrate()
            with target.migration_connection() as write:
                quote = write.dialect.identifier_preparer.quote
                tables = [table for table in Base.metadata.sorted_tables]
                write.exec_driver_sql("LOCK TABLE " + ", ".join(quote(table.name) for table in tables) + " IN ACCESS EXCLUSIVE MODE")
                if any(write.scalar(select(func.count()).select_from(table)) for table in tables):
                    raise SchemaMismatch("TARGET_NOT_EMPTY", "Only an empty PostgreSQL application schema can receive a legacy copy. Existing target data was not replaced.")
                foreign_keys = [(table.name, key["name"]) for table in tables for key in inspect(write).get_foreign_keys(table.name)]
                for table_name, key in foreign_keys:
                    write.exec_driver_sql(f"ALTER TABLE {quote(table_name)} ALTER CONSTRAINT {quote(key)} DEFERRABLE INITIALLY DEFERRED")
                write.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")
                counts = {}
                for destination in tables:
                    if destination.name not in metadata.tables:
                        continue
                    table, copied = metadata.tables[destination.name], 0
                    for partition in read.execute(select(table)).mappings().partitions(500):
                        rows = []
                        for row in partition:
                            values = dict(row)
                            for column in destination.columns:
                                value = values.get(column.name)
                                if isinstance(column.type, DateTime) and column.type.timezone and isinstance(value, datetime) and value.tzinfo is None:
                                    values[column.name] = value.replace(tzinfo=UTC)
                            rows.append(values)
                        if rows:
                            write.execute(destination.insert(), rows)
                            copied += len(rows)
                    if write.scalar(select(func.count()).select_from(destination)) != copied:
                        raise SchemaMismatch("LEGACY_COUNT_MISMATCH", "A copied table did not match the snapshot row count; the target transaction was rolled back.")
                    counts[destination.name] = copied
                write.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
                for table_name, key in foreign_keys:
                    write.exec_driver_sql(f"ALTER TABLE {quote(table_name)} ALTER CONSTRAINT {quote(key)} NOT DEFERRABLE INITIALLY IMMEDIATE")
                with Session(bind=write) as session:
                    heads = session.scalars(select(AuditHead)).all()
                    for head in heads:
                        tenant_id, scope = head.scope_key.split(":", 1)
                        if not audit.verify_chain(session, tenant_id, None if scope == "system" else scope)["valid"]:
                            raise SchemaMismatch("LEGACY_AUDIT_INVALID", "A copied audit chain failed validation; the target transaction was rolled back.")
                    if session.scalar(select(func.count()).select_from(Original)) != originals_checked:
                        raise SchemaMismatch("LEGACY_ORIGINAL_COUNT", "The original-object count did not match the verified snapshot.")
            return {"source_revision": revision, "target_revision": target.schema_status()["required_revision"], "rows": counts, "originals_verified": originals_checked, "audit_scopes_verified": len(heads), "backup_sha256": file_hash(backup_path)[0], "source_unchanged": True, "storage": "Existing immutable storage root retained; no evidence bytes were rewritten."}
    finally:
        source.dispose()
        target.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--services-stopped", action="store_true", help="Confirm source API/worker are stopped for cutover.")
    args = parser.parse_args()
    if not args.services_stopped:
        parser.error("Stop the source API/worker, then pass --services-stopped. The source file and evidence are retained.")
    try:
        print(json.dumps(transfer_sqlite(args.source, args.storage_root, args.backup, Settings()), indent=2))
    except SchemaMismatch as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
