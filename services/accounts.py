"""SQLite accounts and one-time provisioning for local dashboard access."""

import hashlib
import hmac
import secrets

from schemas import UserRole
from services.governance import database

DEFAULT_ACCOUNTS = (
    ("viewer@dashboard", UserRole.VIEW_ONLY),
    ("admin@dashboard", UserRole.INFRA_ADMIN),
)
PASSWORD_ITERATIONS = 600_000


def password_hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)


def initialize_accounts() -> None:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                email TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                password_iterations INTEGER NOT NULL
            )
        """)
        db.execute("CREATE TABLE IF NOT EXISTS account_migrations (name TEXT PRIMARY KEY)")
        # Provision once per database. A deliberately removed account stays removed.
        if db.execute("SELECT 1 FROM account_migrations WHERE name = 'default_accounts'").fetchone():
            return
        for email, role in DEFAULT_ACCOUNTS:
            salt = secrets.token_bytes(16)
            db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?, ?, ?, ?)", (
                email, role.value, salt, password_hash("123", salt, PASSWORD_ITERATIONS), PASSWORD_ITERATIONS,
            ))
        db.execute("INSERT INTO account_migrations VALUES ('default_accounts')")


def authenticate_account(email: str, password: str) -> UserRole | None:
    with database() as db:
        initialized = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
        ).fetchone()
    if not initialized:
        initialize_accounts()
    with database() as db:
        row = db.execute(
            "SELECT role, salt, password_hash, password_iterations FROM accounts WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        return None
    role, salt, expected, iterations = row
    if hmac.compare_digest(password_hash(password, salt, iterations), expected):
        return UserRole(role)
    return None
