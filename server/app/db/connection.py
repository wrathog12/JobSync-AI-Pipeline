"""The connection, the schema, and the migration ladder.

`sqlite3` ships with Python, and this build already has FTS5 and JSON1 compiled
in — so persistence costs no new dependency and nothing to host. The "database
server" is a file next to the process.

Three decisions that look lazy and are not:

**Records are stored as JSON in a `data` column**, with only the fields we filter
on promoted to real columns. The access pattern is "load one person's entire
career once at startup": there is no join to optimise and no second user to
isolate. Normalising `Employment` across six tables would triple this file, buy a
JOIN nobody runs, and turn every Pydantic field addition into a migration.

**The derived layers are not stored at all.** L3 evidence and L4 graph are rebuilt
from L2 on load. Persisting a cache you can regenerate in microseconds only gives
you a cache that can disagree with its source — and L3/L4 disagreeing with L2 is
how retrieval starts citing evidence for a record that was superseded.

**Everything goes through one connection behind a lock.** FastAPI runs sync
endpoints in a threadpool, so `check_same_thread=False` is required; the lock is
what makes that safe. For a single user the contention is zero, and one connection
means one WAL writer, which is the configuration SQLite is happiest in.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

#: Each entry is one irreversible step. Append, never edit — an edited migration
#: has already run on the developer's machine and will never run again, so the
#: schema silently diverges between the two databases that matter most.
MIGRATIONS: list[str] = [
    # ── v1: the layers that are not derived ──
    """
    -- L0. A singleton by construction: this database holds one person, and the
    -- CHECK is what makes a second row a loud error rather than a quiet second
    -- identity for the L0 lock to defend.
    CREATE TABLE identity (
        id         INTEGER PRIMARY KEY CHECK (id = 1),
        locked     INTEGER NOT NULL DEFAULT 0,
        data       TEXT    NOT NULL,
        updated_at TEXT    NOT NULL
    );

    -- L1.
    CREATE TABLE profile (
        id         INTEGER PRIMARY KEY CHECK (id = 1),
        data       TEXT    NOT NULL,
        updated_at TEXT    NOT NULL
    );

    -- L2. `superseded_by` is promoted out of the JSON because every read filters
    -- on it: a superseded record must stay on disk for the audit trail and must
    -- never reach retrieval.
    CREATE TABLE ledger_record (
        id            TEXT PRIMARY KEY,
        kind          TEXT NOT NULL
                      CHECK (kind IN ('employment', 'education', 'project', 'credential')),
        superseded_by TEXT,
        data          TEXT NOT NULL,
        created_at    TEXT NOT NULL
    );
    CREATE INDEX ledger_record_kind ON ledger_record (kind);

    -- L4, declared skills only. The rest of L4 is derived.
    CREATE TABLE declared_skill (
        id   TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        data TEXT NOT NULL
    );

    -- L5. The flywheel, and the only layer whose value grows with use — losing it
    -- to a restart would reset the thing the system is supposed to accumulate.
    CREATE TABLE approved_answer (
        id                    TEXT PRIMARY KEY,
        canonical_question_id TEXT NOT NULL,
        company_id            TEXT,
        data                  TEXT NOT NULL,
        approved_at           TEXT NOT NULL
    );
    CREATE INDEX approved_answer_lookup
        ON approved_answer (canonical_question_id, company_id);

    -- Staging, not memory. Here anyway, because `/confirm` refuses to commit once
    -- the source document is gone (it has no haystack for the verbatim check) and
    -- a structuring pass costs real money to repeat. A restart mid-review used to
    -- throw both away.
    CREATE TABLE document (
        doc_id     TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE candidate (
        doc_id     TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]


class Database:
    """A single serialised connection. Not a connection pool, on purpose."""

    def __init__(self, conn: sqlite3.Connection, path: str) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self.path = path

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One atomic write. Rolls back on any exception.

        Callers save whole layers inside a single `tx()` rather than row by row:
        a half-written ledger is worse than an unwritten one, because the missing
        half is invisible and the present half looks authoritative.
        """
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()


#: Process-wide handle. `None` means persistence is off, which is a supported
#: configuration and not an error — tests and the fixture demo both want it.
_DB: Database | None = None


def open_db(path: str | None) -> Database | None:
    """Open (and migrate) the database. `None` or an empty path disables storage.

    `:memory:` gives a fresh, private database per call, which is what the test
    suite uses: the persistence code still executes end to end, so a broken save
    fails a test rather than waiting for someone to restart the server.
    """
    global _DB
    if not path:
        _DB = None
        return None

    if path != ":memory:":
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        # WAL lets the viewer read while a confirmation writes, and survives a
        # hard kill of the process — which is how this server usually stops.
        # NORMAL rather than FULL: with WAL that is durable across a crash and
        # only loses the last commit on OS-level power loss.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    _migrate(conn)
    _DB = Database(conn, path)
    return _DB


def _migrate(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for target, script in enumerate(MIGRATIONS, start=1):
        if version >= target:
            continue
        conn.executescript(script)
        # Not a bind parameter: PRAGMA does not take them. `target` is a loop
        # index over a module constant, so there is nothing here to inject.
        conn.execute(f"PRAGMA user_version = {target}")
        conn.commit()


def get_db() -> Database | None:
    return _DB


def close_db() -> None:
    global _DB
    if _DB is not None:
        _DB.close()
        _DB = None


__all__ = ["Database", "MIGRATIONS", "open_db", "get_db", "close_db"]
