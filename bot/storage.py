"""SQLite persistence: whitelist, settings, hourly rate limits."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Storage:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS whitelist (
                    chat_id INTEGER PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id INTEGER PRIMARY KEY,
                    last_ts REAL NOT NULL
                );
                """
            )
            cur = conn.execute("SELECT COUNT(*) AS c FROM settings")
            if cur.fetchone()["c"] == 0:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('enabled', '1')"
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('hashtag', '#predict_week')"
                )

    def seed_whitelist(self, chat_ids: frozenset[int]) -> None:
        if not chat_ids:
            return
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO whitelist (chat_id) VALUES (?)",
                [(cid,) for cid in chat_ids],
            )

    def is_whitelisted(self, chat_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM whitelist WHERE chat_id = ? LIMIT 1", (chat_id,)
            ).fetchone()
        return row is not None

    def whitelist_add(self, chat_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO whitelist (chat_id) VALUES (?)", (chat_id,)
            )

    def whitelist_remove(self, chat_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM whitelist WHERE chat_id = ?", (chat_id,))
            return cur.rowcount > 0

    def whitelist_list(self) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT chat_id FROM whitelist ORDER BY chat_id"
            ).fetchall()
        return [int(r["chat_id"]) for r in rows]

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def is_enabled(self) -> bool:
        return self.get_setting("enabled", "1") == "1"

    def set_enabled(self, on: bool) -> None:
        self.set_setting("enabled", "1" if on else "0")

    def get_hashtag(self) -> str:
        return self.get_setting("hashtag", "#predict_week").strip()

    def set_hashtag(self, tag: str) -> None:
        t = tag.strip()
        if not t.startswith("#"):
            t = "#" + t
        self.set_setting("hashtag", t)

    def rate_limit_seconds_left(self, user_id: int, period_sec: int = 60) -> int:
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_ts FROM rate_limits WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            return 0
        elapsed = now - float(row["last_ts"])
        if elapsed >= period_sec:
            return 0
        return int(period_sec - elapsed)

    def touch_rate_limit(self, user_id: int) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO rate_limits (user_id, last_ts) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_ts = excluded.last_ts
                """,
                (user_id, now),
            )
