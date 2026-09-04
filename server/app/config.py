"""Settings. Read from the environment or `server/.env` (gitignored).

**The API key here is a development convenience, not the production path.**
JobSync is BYOK: in production the key belongs to the user, arrives with the
request, and is never persisted server-side. So nothing in the pipeline may read
this setting directly — it is only ever a *fallback* inside
`llm.keys.resolve_key`, and `require_user_key` turns it off entirely.

Getting this seam wrong is expensive to undo: a module that reads a global key at
import time cannot later serve two users with two keys, and every call site has
to be rewritten.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── LLM access ──
    gemini_api_key: str | None = None
    """DEV ONLY. In production the user supplies their own key per request."""

    require_user_key: bool = False
    """Set true in production: refuses to fall back to the server's own key."""

    # ── models ──
    #
    # Two tiers, because the workloads are genuinely different. Classification and
    # tagging are high-volume closed-list picks where a cheap model is not a
    # compromise; prose generation is where quality shows. Which model wins for
    # generation is an empirical question for the eval set (step 7), not an
    # assumption — so both are configurable.
    llm_model_fast: str = "gemini-2.5-flash"
    llm_model_strong: str = "gemini-2.5-pro"

    # ── budgets ──
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    """Transient 5xx and 429 only. A schema failure is not retried — see gemini.py."""

    llm_max_output_tokens: int = 2048
    """A hard ceiling. The user is paying, so a runaway response is their money."""

    thinking_budget_fast: int = 0
    """0 disables thinking on 2.5 Flash. Structuring and tagging do not need it,
    and on BYOK an invisible reasoning bill is a bad surprise."""

    # ── storage ──
    db_path: str = "data/jobsync.db"
    """One SQLite file, relative to wherever the server is started.

    `:memory:` gives a fresh private database per process — what the test suite
    uses, so the persistence code still runs end to end. Empty disables storage
    entirely, which is supported: memory then lives and dies with the process.
    """


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
