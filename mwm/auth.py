from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

from .config import Config
from .db import connect

ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(iterations))
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def read_cookie(header: str, name: str = "mwm_session") -> str | None:
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    return cookie[name].value if name in cookie else None


def create_session(config: Config, member_id: int | None = None) -> tuple[str, dict]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    db = connect(config.database_path)
    try:
        db.execute(
            "INSERT INTO sessions(token_hash,member_id,csrf_token,expires_at) VALUES (?,?,?,?)",
            (token_hash(token), member_id, csrf, expires.strftime("%Y-%m-%d %H:%M:%S")),
        )
    finally:
        db.close()
    return token, {"member_id": member_id, "csrf_token": csrf, "adult_ok": 0}


def load_session(config: Config, token: str | None) -> tuple[dict | None, dict | None]:
    if not token:
        return None, None
    db = connect(config.database_path)
    try:
        row = db.execute(
            "SELECT s.*,m.email,m.display_name,m.role,m.status,m.interests_public,m.show_adult FROM sessions s LEFT JOIN members m ON m.id=s.member_id WHERE s.token_hash=? AND s.expires_at>CURRENT_TIMESTAMP",
            (token_hash(token),),
        ).fetchone()
        if not row or (row["member_id"] and row["status"] != "active"):
            return None, None
        db.execute("UPDATE sessions SET last_seen_at=CURRENT_TIMESTAMP WHERE token_hash=?", (token_hash(token),))
        session = {"member_id": row["member_id"], "csrf_token": row["csrf_token"], "adult_ok": row["adult_ok"]}
        member = None if not row["member_id"] else {key: row[key] for key in ("member_id", "email", "display_name", "role", "interests_public", "show_adult")}
        return session, member
    finally:
        db.close()


def destroy_session(config: Config, token: str | None) -> None:
    if not token:
        return
    db = connect(config.database_path)
    try:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    finally:
        db.close()


def cookie_header(config: Config, token: str, *, clear: bool = False) -> tuple[str, str]:
    value = f"mwm_session={token}; Path=/; HttpOnly; SameSite=Lax"
    if config.secure_cookies:
        value += "; Secure"
    value += "; Max-Age=0" if clear else "; Max-Age=2592000"
    return "Set-Cookie", value


def ensure_admin(config: Config) -> None:
    if not config.admin_email or not config.admin_password:
        return
    db = connect(config.database_path)
    try:
        db.execute(
            "INSERT INTO members(email,password_hash,display_name,role,email_verified_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(email) DO NOTHING",
            (config.admin_email, hash_password(config.admin_password), "Administrator", "admin"),
        )
    finally:
        db.close()
