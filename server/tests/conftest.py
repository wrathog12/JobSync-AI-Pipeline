"""Test-wide setup.

`DB_PATH=:memory:` rather than empty, so persistence still *runs* under test. An
empty path disables storage, and disabling it would mean every existing HTTP test
silently stops exercising the save path — a broken `save_memory` would then pass
CI and fail on the user's next restart, which is the one place it is hardest to
notice and most expensive to lose.

Set before anything imports `app.config`, because `get_settings()` is
`lru_cache`d: the first read wins for the whole session.
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PATH", ":memory:")
