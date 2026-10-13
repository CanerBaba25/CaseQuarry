"""Explicit IANA zone names and local calendar boundaries for manual due dates."""

from datetime import UTC
from functools import lru_cache
from importlib.resources import files
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def names():
    # Bundled tzdata supplies the same IANA database on Windows and server hosts.
    return tuple(sorted(name for name in files("tzdata").joinpath("zones").read_text(encoding="utf-8").splitlines() if name not in {"localtime", "Factory"}))


def validate(value):
    if not isinstance(value, str) or len(value) > 100 or value not in names():
        raise ValueError("Choose a supported IANA timezone, such as America/Toronto or UTC.")
    return value


def local_today(value, instant):
    # A corrupt stored preference must fail instead of silently changing deadlines.
    zone = _zone(validate(value))
    instant = instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant
    return instant.astimezone(zone).date()


@lru_cache(maxsize=512)
def _zone(value):
    with files("tzdata").joinpath("zoneinfo", *value.split("/")).open("rb") as stream:
        return ZoneInfo.from_file(stream, key=value)
