"""Durable storage. One SQLite file, no server, no new dependency."""

from .connection import MIGRATIONS, Database, close_db, get_db, open_db
from .repository import (
    delete_candidate,
    delete_document,
    load_all,
    load_memory,
    load_staging,
    save_candidate,
    save_document,
    save_memory,
    stats,
    wipe_memory,
)

__all__ = [
    "Database",
    "MIGRATIONS",
    "open_db",
    "get_db",
    "close_db",
    "load_all",
    "load_memory",
    "load_staging",
    "save_memory",
    "wipe_memory",
    "save_document",
    "delete_document",
    "save_candidate",
    "delete_candidate",
    "stats",
]
