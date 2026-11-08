"""Pluggable persistence.

Default: a JSON file (data/store.json). Set DATABASE_URL to switch to
PostgreSQL (same interface, JSONB payloads). Both stores expose the same
tiny key/value API so the rest of the app never cares which one is active.
"""

import json
import os
import threading
import uuid
from pathlib import Path

from . import config

_LOCK = threading.Lock()
_STORE = None


class JsonStore:
    """Single-file JSON store. Writes are atomic (temp file + rename)."""

    def __init__(self, path: str | None = None):
        self.path = Path(path or config.STORE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, dict]] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self._data = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, default=str))
        os.replace(tmp, self.path)

    def get(self, collection: str, key: str, default=None):
        return self._data.get(collection, {}).get(key, default)

    def put(self, collection: str, key: str, value: dict) -> None:
        with _LOCK:
            self._data.setdefault(collection, {})[key] = value
            self._save()

    def delete(self, collection: str, key: str) -> None:
        with _LOCK:
            self._data.get(collection, {}).pop(key, None)
            self._save()

    def list(self, collection: str) -> list[tuple[str, dict]]:
        return list(self._data.get(collection, {}).items())

    def append(self, collection: str, value: dict) -> str:
        key = value.get("id") or uuid.uuid4().hex[:12]
        value = dict(value)
        value.setdefault("id", key)
        self.put(collection, key, value)
        return key

    def clear(self) -> None:
        with _LOCK:
            self._data = {}
            self._save()


class PostgresStore:
    """PostgreSQL store with the same interface (one kv table, JSONB)."""

    def __init__(self, dsn: str):
        import psycopg

        self._psycopg = psycopg
        self.dsn = dsn
        self._ensure_table()

    def _conn(self):
        return self._psycopg.connect(self.dsn, autocommit=True)

    def _ensure_table(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS kv_store "
                "(collection TEXT NOT NULL, key TEXT NOT NULL, "
                "value JSONB NOT NULL, PRIMARY KEY (collection, key))"
            )

    def get(self, collection: str, key: str, default=None):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM kv_store WHERE collection=%s AND key=%s",
                (collection, key),
            )
            row = cur.fetchone()
            return row[0] if row else default

    def put(self, collection: str, key: str, value: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kv_store (collection, key, value) VALUES (%s, %s, %s) "
                "ON CONFLICT (collection, key) DO UPDATE SET value=EXCLUDED.value",
                (collection, key, json.dumps(value, default=str)),
            )

    def delete(self, collection: str, key: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kv_store WHERE collection=%s AND key=%s",
                (collection, key),
            )

    def list(self, collection: str) -> list[tuple[str, dict]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT key, value FROM kv_store WHERE collection=%s ORDER BY key",
                (collection,),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    def append(self, collection: str, value: dict) -> str:
        key = value.get("id") or uuid.uuid4().hex[:12]
        value = dict(value)
        value.setdefault("id", key)
        self.put(collection, key, value)
        return key

    def clear(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE kv_store")


def get_store():
    """Return the configured store (singleton). Postgres when DATABASE_URL
    is set and psycopg imports; otherwise the JSON file store."""
    global _STORE
    if _STORE is not None:
        return _STORE
    if config.DATABASE_URL:
        try:
            _STORE = PostgresStore(config.DATABASE_URL)
            return _STORE
        except Exception as exc:  # noqa: BLE001 - Postgres is optional; fall back to JSON
            print(f"[store] Postgres unavailable ({exc}); using JSON store.")
    _STORE = JsonStore()
    return _STORE


def set_store(store) -> None:
    """Override the store (used by tests)."""
    global _STORE
    _STORE = store
