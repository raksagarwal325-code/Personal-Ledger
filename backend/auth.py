"""Phase 6 — JWT-based custom auth (email + password + bcrypt + JWT).

All admin endpoints re-verify the JWT + role='admin' server-side. Frontend
hiding is not sufficient.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60 * 8  # 8h — Rakshit runs a single-tenant app
REFRESH_TOKEN_DAYS = 30


def get_jwt_secret() -> str:
    s = os.environ.get("JWT_SECRET")
    if not s:
        raise HTTPException(500, "JWT_SECRET is not configured.")
    return s


# ─── Passwords ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ─── Tokens ─────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    if payload.get("type") != expected_type:
        raise HTTPException(401, "Invalid token type")
    return payload


# ─── User document ──────────────────────────────────────────────────────────

def new_user_doc(email: str, password: str, name: str = "", role: str = "admin") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "name": name or email.split("@")[0],
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_login_at": None,
    }


def user_public(doc: dict) -> dict:
    """Shape a user doc for JSON responses — strip password_hash."""
    return {
        "id": doc.get("id"),
        "email": doc.get("email"),
        "name": doc.get("name") or "",
        "role": doc.get("role") or "admin",
        "created_at": doc.get("created_at"),
        "last_login_at": doc.get("last_login_at"),
    }


# ─── Cookie helpers ─────────────────────────────────────────────────────────

def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key="access_token", value=access_token, httponly=True,
        secure=False, samesite="lax", max_age=ACCESS_TOKEN_MINUTES * 60, path="/",
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token, httponly=True,
        secure=False, samesite="lax", max_age=REFRESH_TOKEN_DAYS * 86400, path="/",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


# ─── FastAPI dependencies ───────────────────────────────────────────────────

def _extract_token(request: Request) -> Optional[str]:
    tok = request.cookies.get("access_token")
    if tok:
        return tok
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def get_current_user_from_db(request: Request, db) -> dict:
    tok = _extract_token(request)
    if not tok:
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(tok, expected_type="access")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def require_admin(request: Request, db) -> dict:
    """Every admin endpoint uses this — never trust the frontend."""
    user = await get_current_user_from_db(request, db)
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin privileges required.")
    return user
