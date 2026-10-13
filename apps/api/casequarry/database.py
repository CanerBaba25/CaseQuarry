"""Database sessions and serialized, versioned schema setup."""

import argparse
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from . import ai_models, production_models, provider_models, sync_models, workflow_models  # noqa: F401 - register the complete schema
from .config import Settings
from .models import Base

HEAD_REVISION = "0007_task_versions"
CORE_REVISION = "0001_core"
_MIGRATION_LOCK = threading.RLock()
_POSTGRES_LOCK_KEY = 0x4351534348454D41


class SchemaMismatch(RuntimeError):
    def __init__(self, code: str, message: str, diagnostics=()):
        self.code, self.diagnostics = code, list(diagnostics)
        suffix = "; ".join(self.diagnostics[:12])
        if len(self.diagnostics) > 12:
            suffix += f"; {len(self.diagnostics) - 12} additional schema differences"
        super().__init__(f"{code}: {message}" + (f" ({suffix})" if suffix else ""))


def migration_root():
    package = Path(__file__).resolve().parent / "migrations"
    source = Path(__file__).resolve().parents[3] / "migrations"
    for candidate in (package, source):
        if (candidate / "env.py").is_file() and (candidate / "schema_signatures.json").is_file():
            return candidate
    raise SchemaMismatch("MIGRATION_RESOURCES_MISSING", "Install a complete CaseQuarry package containing its migration resources.")


def known_schemas():
    return json.loads((migration_root() / "schema_signatures.json").read_text(encoding="utf-8"))


def schema_differences(connection, revision):
    schemas = known_schemas()
    if revision not in schemas:
        return [f"unknown revision {revision}"]
    expected, inspector = schemas[revision], inspect(connection)
    found_tables = set(inspector.get_table_names()) - {"alembic_version"}
    differences = []
    if found_tables != set(expected):
        differences.extend(f"missing table {name}" for name in sorted(set(expected) - found_tables))
        differences.extend(f"unexpected table {name}" for name in sorted(found_tables - set(expected)))
    for name in sorted(found_tables & set(expected)):
        definition = expected[name]
        found = {column["name"]: column for column in inspector.get_columns(name)}
        columns = {column["name"]: column for column in definition["columns"]}
        differences.extend(f"{name}: missing column {column}" for column in sorted(set(columns) - set(found)))
        differences.extend(f"{name}: unexpected column {column}" for column in sorted(set(found) - set(columns)))
        for column in sorted(set(columns) & set(found)):
            actual, desired = found[column], columns[column]
            expected_type = desired["types"].get(connection.dialect.name)
            actual_type = str(actual["type"].compile(dialect=connection.dialect)).upper()
            if actual_type != expected_type:
                differences.append(f"{name}.{column}: expected {expected_type}, found {actual_type}")
            if actual["nullable"] != desired["nullable"]:
                differences.append(f"{name}.{column}: nullability differs")
            if actual.get("default") != desired.get("defaults", {}).get(connection.dialect.name, desired["default"]):
                differences.append(f"{name}.{column}: server default differs")
        if inspector.get_pk_constraint(name)["constrained_columns"] != definition["primary_key"]:
            differences.append(f"{name}: primary key differs")
        unique = sorted(constraint["column_names"] for constraint in inspector.get_unique_constraints(name))
        if unique != definition["unique"]:
            differences.append(f"{name}: unique constraints differ")
        foreign_keys = []
        for key in inspector.get_foreign_keys(name):
            foreign_keys.append({"columns": key["constrained_columns"], "table": key["referred_table"], "referred_columns": key["referred_columns"], "ondelete": key.get("options", {}).get("ondelete"), "onupdate": key.get("options", {}).get("onupdate")})
        if sorted(foreign_keys, key=lambda value: json.dumps(value, sort_keys=True)) != definition["foreign_keys"]:
            differences.append(f"{name}: foreign keys differ")
        indexes = [{"name": index["name"], "columns": index["column_names"], "unique": bool(index["unique"])} for index in inspector.get_indexes(name) if not index.get("duplicates_constraint")]
        if sorted(indexes, key=lambda value: value["name"]) != definition["indexes"]:
            differences.append(f"{name}: indexes differ")
        if inspector.get_check_constraints(name):
            differences.append(f"{name}: unexpected check constraints")
    if connection.dialect.name == "sqlite":
        triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars()
        differences.extend(f"unexpected trigger {name}" for name in triggers)
    return differences


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        kwargs = {"pool_pre_ping": True}
        if settings.database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if settings.database_url.endswith(":memory:") or settings.database_url in {"sqlite://", "sqlite+pysqlite://"}:
                kwargs["poolclass"] = StaticPool
            elif "///" in settings.database_url:
                Path(settings.database_url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(settings.database_url, **kwargs)
        if settings.database_url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def sqlite_setup(connection, _record):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA journal_mode=WAL")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def alembic_config(self, connection=None):
        config = Config()
        config.set_main_option("script_location", str(migration_root()).replace("%", "%%"))
        if connection is not None:
            config.attributes["connection"] = connection
        return config

    @contextmanager
    def migration_connection(self):
        """Serialize Alembic context, plus database-wide DDL across processes."""
        with _MIGRATION_LOCK, self.engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            elif connection.dialect.name == "postgresql":
                connection.begin()
                connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _POSTGRES_LOCK_KEY})
            else:
                raise SchemaMismatch("DATABASE_DIALECT_UNSUPPORTED", "Use PostgreSQL for development/deployment, or an explicit SQLite URL for local QA and legacy recovery.")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def prepare_migration(self, connection, adopt_existing=False):
        heads = MigrationContext.configure(connection).get_current_heads()
        if len(heads) > 1 or heads and heads[0] not in known_schemas():
            raise SchemaMismatch("SCHEMA_REVISION_UNKNOWN", "This database revision does not match the installed release.", heads)
        if heads:
            differences = schema_differences(connection, heads[0])
            if differences:
                raise SchemaMismatch("SCHEMA_DRIFT", "The versioned schema differs from its static migration. Resolve the drift before upgrading.", differences)
            return heads[0]
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        if not tables:
            return None
        if not adopt_existing or self.settings.environment == "production":
            raise SchemaMismatch("SCHEMA_ADOPTION_REQUIRED", "This database has no migration revision. Only an exact known development schema may be adopted using python -m casequarry.database migrate --adopt-existing-development.")
        for revision in sorted(known_schemas(), reverse=True):
            if not schema_differences(connection, revision):
                command.stamp(self.alembic_config(connection), revision)
                return revision
        diagnostics = schema_differences(connection, HEAD_REVISION)
        raise SchemaMismatch("SCHEMA_ADOPTION_REFUSED", "The unversioned development schema does not exactly match a known migration; no revision was stamped.", diagnostics)

    def migrate(self, revision="head", *, adopt_existing=False):
        if revision != "head" and revision not in known_schemas():
            raise SchemaMismatch("SCHEMA_REVISION_UNKNOWN", "Choose head or a known forward migration revision.")
        with self.migration_connection() as connection:
            current = self.prepare_migration(connection, adopt_existing=adopt_existing)
            revisions = sorted(known_schemas())
            if current and revision != "head" and revisions.index(current) > revisions.index(revision):
                raise SchemaMismatch("SCHEMA_DOWNGRADE_REFUSED", "Startup and migration setup never downgrade or discard evidence tables.")
            command.upgrade(self.alembic_config(connection), revision)
            target = HEAD_REVISION if revision == "head" else revision
            differences = schema_differences(connection, target)
            if differences:
                raise SchemaMismatch("SCHEMA_MIGRATION_INVALID", "The migrated schema failed validation; the transaction was rolled back.", differences)
            if target == HEAD_REVISION and compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True}), Base.metadata):
                raise SchemaMismatch("MODEL_SCHEMA_DRIFT", "Application models require a new reviewed static migration.")
        return target

    def initialize(self):
        if self.settings.environment == "test":
            Base.metadata.create_all(self.engine)
        elif self.settings.environment == "production":
            self.require_current_schema()
        else:
            self.migrate(adopt_existing=True)

    def require_current_schema(self):
        with self.engine.connect() as connection:
            heads = MigrationContext.configure(connection).get_current_heads()
            if heads != (HEAD_REVISION,):
                raise SchemaMismatch("SCHEMA_MIGRATION_REQUIRED", "Apply the release migration before starting production: python -m casequarry.database migrate.")
            differences = schema_differences(connection, HEAD_REVISION)
            if differences:
                raise SchemaMismatch("SCHEMA_DRIFT", "Production schema differs from the release migration; startup refused.", differences)
            if compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True}), Base.metadata):
                raise SchemaMismatch("MODEL_SCHEMA_DRIFT", "Application models and the installed migration do not agree.")

    def schema_status(self):
        with self.engine.connect() as connection:
            heads = MigrationContext.configure(connection).get_current_heads()
            return {"revisions": list(heads), "required_revision": HEAD_REVISION, "current": heads == (HEAD_REVISION,) and not schema_differences(connection, HEAD_REVISION)}

    def dispose(self):
        self.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="CaseQuarry database schema operations; connection comes from environment.")
    commands = parser.add_subparsers(dest="action", required=True)
    migrate = commands.add_parser("migrate", help="Apply static forward migrations under a database lock.")
    migrate.add_argument("--adopt-existing-development", action="store_true", help="Adopt only an exact known unversioned development schema.")
    commands.add_parser("status", help="Show the migration revision without connection credentials.")
    args = parser.parse_args()
    database = Database(Settings())
    try:
        if args.action == "migrate":
            revision = database.migrate(adopt_existing=args.adopt_existing_development)
            print(json.dumps({"revision": revision, "status": "migrated"}))
        else:
            print(json.dumps(database.schema_status()))
    except SchemaMismatch as error:
        parser.exit(2, f"{error}\n")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
