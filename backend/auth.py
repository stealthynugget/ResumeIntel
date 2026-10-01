"""Local accounts with Argon2id hashes and database-backed cookie sessions."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException, Request, Response

from .db import connect

COOKIE = "ri_session"
MAX_AGE = 7 * 24 * 60 * 60
HASHER = PasswordHasher()


def _utc(delta=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat()


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_user(row, csrf=None):
    result = {"id": row["id"], "email": row["email"], "display_name": row["display_name"],
              "role": row["role"], "active": bool(row["active"]), "ai_enabled": bool(row["ai_enabled"])}
    if csrf is not None:
        result["csrf_token"] = csrf
    return result


def _origin_ok(request):
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = {str(request.base_url).rstrip("/"), "http://localhost:5173", "http://127.0.0.1:5173"}
    configured = os.getenv("RESUMEINTEL_ALLOWED_ORIGIN", "").strip().rstrip("/")
    if configured:
        allowed.add(configured)
    if origin not in allowed:
        raise HTTPException(403, "Request origin is not allowed")


def check_origin(request):
    _origin_ok(request)


def require_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Sign in to continue")
    with connect() as db:
        row = db.execute("""SELECT u.*,s.csrf_token FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""", (_digest(token), _utc())).fetchone()
    if not row:
        raise HTTPException(401, "Session expired; sign in again")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _origin_ok(request)
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not secrets.compare_digest(supplied, row["csrf_token"]):
            raise HTTPException(403, "Missing or invalid CSRF token")
    return dict(row)


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def session_for(request: Request, response: Response, user):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connect() as db:
        db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
                   (_digest(token), user["id"], csrf, _utc(MAX_AGE)))
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or os.getenv("RESUMEINTEL_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}, path="/")
    return public_user(user, csrf)


def signup(request: Request, response: Response, email: str, display_name: str, password: str):
    _origin_ok(request)
    email = email.strip().lower()
    if len(password) < 12:
        raise HTTPException(422, "Password must have at least 12 characters")
    with connect() as db:
        try:
            cur = db.execute("INSERT INTO users(email,display_name,password_hash,role) VALUES(?,?,?,'recruiter')",
                             (email, display_name.strip(), HASHER.hash(password)))
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "Account already exists") from exc
            raise
        user = db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return session_for(request, response, user)


def signin(request: Request, response: Response, email: str, password: str):
    _origin_ok(request)
    email = email.strip().lower()
    ip = request.client.host if request.client else "unknown"
    with connect() as db:
        db.execute("DELETE FROM login_attempts WHERE created_at < ?", ((datetime.now(timezone.utc) - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S'),))
        attempts = db.execute("SELECT COUNT(*) FROM login_attempts WHERE email=? AND ip=?",
                              (email, ip)).fetchone()[0]
        if attempts >= 5:
            raise HTTPException(429, "Too many sign-in attempts; try again in 15 minutes")
        user = db.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
        valid = False
        if user:
            try:
                valid = HASHER.verify(user["password_hash"], password)
            except (VerifyMismatchError, VerificationError):
                pass
        if not valid:
            db.execute("INSERT INTO login_attempts(email,ip) VALUES(?,?)", (email, ip))
            db.commit()
            raise HTTPException(401, "Invalid email or password")
        db.execute("DELETE FROM login_attempts WHERE email=? AND ip=?", (email, ip))
        if HASHER.check_needs_rehash(user["password_hash"]):
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (HASHER.hash(password), user["id"]))
    return session_for(request, response, user)


def signout(request: Request, response: Response, user):
    token = request.cookies.get(COOKIE, "")
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=? AND user_id=?", (_digest(token), user["id"]))
    response.delete_cookie(COOKIE, path="/")
    return {"signed_out": True}


def change_password(user, current: str, replacement: str, token: str):
    if len(replacement) < 12:
        raise HTTPException(422, "New password must have at least 12 characters")
    try:
        HASHER.verify(user["password_hash"], current)
    except (VerifyMismatchError, VerificationError) as exc:
        raise HTTPException(403, "Current password is incorrect") from exc
    with connect() as db:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (HASHER.hash(replacement), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                   (user["id"], _digest(token)))
    return {"changed": True}


def can_access_owner(user, owner_id):
    return user["role"] == "admin" or owner_id == user["id"]


def check_owner(user, owner_id, label="Resource"):
    if not can_access_owner(user, owner_id):
        raise HTTPException(404, f"{label} not found")
