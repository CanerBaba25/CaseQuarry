"""Run static migrations with a supplied transaction or an operator-owned connection."""

from alembic import context
from casequarry import ai_models, production_models, provider_models, sync_models, workflow_models  # noqa: F401 - register all application tables
from casequarry.config import Settings
from casequarry.database import Database
from casequarry.models import Base

config = context.config
target_metadata = Base.metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=Settings().database_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    database = Database(Settings())
    try:
        with database.migration_connection() as connection:
            database.prepare_migration(connection, adopt_existing=False)
            migrate(connection)
    finally:
        database.dispose()
