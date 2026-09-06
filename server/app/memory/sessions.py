"""The registry of live L6 sessions.

A process dict, mirrored to the `session` table by the endpoints that change one
(see `db/repository.save_session`). The dict is still the source of truth in
process; the table is what makes a restart invisible.

That mirroring is not tidiness. An application is filled over half an hour, and a
session holds the job description the user pasted, every answer already given, and
the spent-evidence ledger that stops page 6 retelling page 2's story. Losing it to
a restart was the one failure in this system that destroyed work the user could not
cheaply redo — and it got worse the moment the JD became something they type in by
hand.

Sessions are still sealed off from L0-L5: nothing here is ever merged into memory,
and `test_session_never_writes_to_durable_memory` is what keeps it that way.

PHASE 2 TASK: the extension's background service worker becomes the owner of
session state, with the server holding it only as a cache. That matters for a
second device, not for a restart.
"""

from __future__ import annotations

import uuid

from ..schemas.common import GenerationMode
from ..schemas.session import ApplicationSession, jd_fingerprint

#: Bounded so a long-running dev server can't grow without limit.
MAX_SESSIONS = 100


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ApplicationSession] = {}

    def create(
        self,
        *,
        jd_text: str | None = None,
        mode: GenerationMode = GenerationMode.STRICT,
        company: str | None = None,
        role_title: str | None = None,
        origin: str | None = None,
    ) -> ApplicationSession:
        session = ApplicationSession(
            session_id=f"sess_{uuid.uuid4().hex[:10]}",
            mode=mode,
            company=company,
            role_title=role_title,
            origin=origin,
        )
        session.set_jd(jd_text)
        self._sessions[session.session_id] = session
        self._evict()
        return session

    def put(self, session: ApplicationSession) -> None:
        """Insert a session exactly as given. For the loader restoring one from
        disk — `create` mints a new id, which would orphan the stored row."""
        self._sessions[session.session_id] = session
        self._evict()

    def get(self, session_id: str | None) -> ApplicationSession | None:
        return self._sessions.get(session_id) if session_id else None

    def find_by_jd(self, jd_text: str | None) -> ApplicationSession | None:
        """Reattach to a session after navigation, when the URL has changed but the JD hasn't."""
        if not jd_text:
            return None
        fp = jd_fingerprint(jd_text)
        return next(
            (s for s in reversed(list(self._sessions.values())) if s.jd_fingerprint == fp),
            None,
        )

    def get_or_create(
        self,
        session_id: str | None = None,
        *,
        jd_text: str | None = None,
        mode: GenerationMode = GenerationMode.STRICT,
    ) -> ApplicationSession:
        session = self.get(session_id) or self.find_by_jd(jd_text)
        if session is None:
            return self.create(jd_text=jd_text, mode=mode)
        # A JD arriving on a later page (or a first page that lacked it) fills a
        # gap; it must not silently overwrite a JD already anchoring the session.
        if jd_text and not session.jd_text:
            session.set_jd(jd_text)
        return session

    def all(self) -> list[ApplicationSession]:
        return list(reversed(list(self._sessions.values())))

    def drop(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def clear(self) -> None:
        self._sessions.clear()

    def _evict(self) -> None:
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))


SESSIONS = SessionStore()


def get_sessions() -> SessionStore:
    return SESSIONS


__all__ = ["SessionStore", "SESSIONS", "get_sessions", "MAX_SESSIONS"]
