from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings
from .models import Base


class Database:
    def __init__(self, settings: Settings):
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

    def initialize(self):
        Base.metadata.create_all(self.engine)

    def dispose(self):
        self.engine.dispose()
