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


def list_accounts():
    initialize_accounts()
    with database() as db:
        return [{"email": email, "role": role} for email, role in
                db.execute("SELECT email, role FROM accounts ORDER BY email")]


def save_account(email, role, password, actor, original=None):
    from schemas import AuditActionType, AuditLogEntry

    initialize_accounts()
    if password is not None:
        salt = secrets.token_bytes(16)
        credentials = (salt, password_hash(password, salt, PASSWORD_ITERATIONS), PASSWORD_ITERATIONS)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = None
        if original is not None:
            row = db.execute("SELECT role, salt, password_hash, password_iterations FROM accounts WHERE email=?",
                             (original,)).fetchone()
            if row is None:
                raise LookupError("Usuário não encontrado")
            previous = {"email": original, "role": row[0]}
            if row[0] == UserRole.INFRA_ADMIN and role != UserRole.INFRA_ADMIN:
                count = db.execute("SELECT COUNT(*) FROM accounts WHERE role=?", (UserRole.INFRA_ADMIN,)).fetchone()[0]
                if count == 1:
                    raise ValueError("Mantenha pelo menos um administrador")
            if password is None:
                credentials = row[1:]
        elif password is None:
            raise ValueError("Informe uma senha para o novo usuário")
        if email != original and db.execute("SELECT 1 FROM accounts WHERE email=?", (email,)).fetchone():
            raise ValueError("Este e-mail já está cadastrado")
        if original is None:
            db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?)", (email, role.value, *credentials))
        else:
            db.execute("UPDATE accounts SET email=?, role=?, salt=?, password_hash=?, password_iterations=? WHERE email=?",
                       (email, role.value, *credentials, original))
        result = {"email": email, "role": role.value}
        entry = AuditLogEntry(user_id=actor, action_type=AuditActionType.CONFIG_CHANGE,
                              targeted_metric=f"account.{original or email}", previous_value=previous,
                              new_value={**result, "password_changed": password is not None})
        db.execute("INSERT INTO audit VALUES (?)", (entry.model_dump_json(),))
        return result
