from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import psycopg


class HybridRow(dict):
    """Row compatible avec sqlite3.Row: accès par nom et par position."""

    def __init__(self, columns, values):
        values = [float(value) if isinstance(value, Decimal) else value for value in values]
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def hybrid_row(cursor):
    columns = [column.name for column in (cursor.description or [])]

    def make_row(values):
        return HybridRow(columns, values)

    return make_row


class CloudConnection:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _sql(statement):
        return statement.replace("?", "%s")

    def execute(self, statement, params=()):
        return self.connection.execute(self._sql(statement), params)

    def executemany(self, statement, params):
        with self.connection.cursor() as cursor:
            cursor.executemany(self._sql(statement), params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()


@contextmanager
def db():
    url = os.environ.get("DADOU_DATABASE_URL")
    if not url:
        raise RuntimeError("La base de données en ligne n’est pas configurée.")
    connection = psycopg.connect(
        url,
        connect_timeout=10,
        prepare_threshold=None,
        row_factory=hybrid_row,
    )
    wrapper = CloudConnection(connection)
    try:
        connection.execute("SET LOCAL search_path TO dadou,public")
        yield wrapper
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def setting_get(key: str, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    value = row["value"]
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def setting_set(key: str, value) -> None:
    encoded = json.dumps(value, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, encoded),
        )


def password_is_configured() -> bool:
    return bool(setting_get("password_hash"))


def set_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    setting_set("password_hash", f"{salt.hex()}:{digest.hex()}")
    recovery = "-".join(secrets.token_hex(2).upper() for _ in range(4))
    setting_set("recovery_hash", hashlib.sha256(recovery.encode("utf-8")).hexdigest())
    return recovery


def verify_password(password: str) -> bool:
    stored = setting_get("password_hash", "")
    if not stored or ":" not in stored:
        return False
    salt_hex, digest_hex = stored.split(":", 1)
    check = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 310_000
    )
    return hmac.compare_digest(check.hex(), digest_hex)


def verify_recovery(code: str) -> bool:
    expected = setting_get("recovery_hash", "")
    actual = hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()
    return bool(expected) and hmac.compare_digest(actual, expected)


def row_dict(row):
    return dict(row) if row is not None else None


def next_code(conn) -> str:
    number = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM items").fetchone()[0]
    return f"DAD-{number:05d}"


def safe_date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except Exception as exc:
        raise ValueError(f"La date « {field} » est invalide.") from exc


def money(value, field: str) -> float:
    try:
        number = round(float(value), 2)
    except Exception as exc:
        raise ValueError(f"Le montant « {field} » est invalide.") from exc
    if number < 0:
        raise ValueError(f"Le montant « {field} » ne peut pas être négatif.")
    return number
