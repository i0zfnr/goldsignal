import getpass
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from threading import Lock
from collections import deque

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

from .config import MODE, utc_now
from .store import transaction

router = APIRouter()
COOKIE = "goldsignal_session"
MODEL = "gemini-2.5-flash-lite"
attempts = {"admin": deque(), "viewer": deque()}
attempt_lock = Lock()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def secure_cookie():
    return os.getenv("SECURE_COOKIE", "0") == "1"


def identity(request):
    token = request.cookies.get(COOKIE, "")
    if len(token) != 43:
        return None
    with transaction() as store:
        session = store.get("login_session", digest(token))
        if not session or session["expires"] <= utc_now():
            return None
        if session["role"] == "viewer":
            invite = store.get("access_key", session["id"])
            if not invite or invite["revoked"]:
                return None
        return session


def admin(request):
    actor = identity(request)
    if not actor or actor["role"] != "admin":
        raise HTTPException(403, "Admin sign-in required.")
    return actor


def allow_attempt(role):
    now = time.monotonic()
    with attempt_lock:
        queue = attempts[role]
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if len(queue) >= (10 if role == "admin" else 40):
            raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")
        queue.append(now)


def encryption():
    return Fernet(os.environ["GOLDSIGNAL_SECRET_KEY"].encode())


class Login(BaseModel):
    credential: SecretStr = Field(min_length=1, max_length=256)


class AdminLogin(Login):
    email: str = Field(min_length=3, max_length=254)


@router.get("/api/auth/session")
def current(request: Request):
    actor = identity(request)
    return {"role": actor["role"] if actor else
            "demo" if MODE == "demo" and not os.getenv("ADMIN_PASSWORD_HASH") else None}


def login(role, credential, response, email=None):
    allow_attempt(role)
    now = utc_now()
    duration = 12 * 3600 if role == "admin" else 30 * 86400
    with transaction() as store:
        if role == "admin":
            config = os.getenv("ADMIN_PASSWORD_HASH", "")
            if not config:
                raise HTTPException(503, "Admin access requires local setup.")
            salt, expected = config.split(":", 1)
            password_ok = hmac.compare_digest(password_hash(credential, salt), expected)
            valid = password_ok and hmac.compare_digest(
                digest(email.strip().lower()), digest(os.environ["ADMIN_EMAIL"].strip().lower()))
            subject = "admin"
        else:
            subject = digest(credential.strip())
            grant = store.get("access_key", subject)
            valid = grant and not grant["revoked"]
        if not valid:
            raise HTTPException(401, "Invalid credential.")
        token = secrets.token_urlsafe(32)
        store.put("login_session", digest(token), dict(id=subject, role=role, expires=now + duration))
    response.set_cookie(COOKIE, token, httponly=True, secure=secure_cookie(), samesite="strict", max_age=duration)
    return {"role": role}


@router.post("/api/auth/admin")
def login_admin(body: AdminLogin, response: Response):
    return login("admin", body.credential.get_secret_value(), response, body.email)


@router.post("/api/auth/viewer")
def login_viewer(body: Login, response: Response):
    return login("viewer", body.credential.get_secret_value(), response)


@router.delete("/api/auth/session")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, "")
    if len(token) == 43:
        with transaction() as store:
            store.delete("login_session", digest(token))
    response.delete_cookie(COOKIE, httponly=True, secure=secure_cookie(), samesite="strict")
    return {"signed_out": True}


class Invite(BaseModel):
    label: str = Field(min_length=1, max_length=80, pattern=r"\S")


class Gemini(BaseModel):
    api_key: SecretStr | None = Field(default=None, min_length=12, max_length=256)
    enabled: bool


@router.get("/api/admin/settings")
def settings(request: Request):
    admin(request)
    with transaction() as store:
        config = store.get("ai", "gemini", {})
        grants = store.all("access_key")
    return {"configured": bool(config.get("ciphertext")), "enabled": bool(config.get("enabled")),
            "model": MODEL, "keys": sorted(grants, key=lambda item: item["created"], reverse=True)}


@router.post("/api/admin/keys", status_code=201)
def create_key(body: Invite, request: Request):
    admin(request)
    secret = "gs_" + secrets.token_urlsafe(24)
    subject = digest(secret)
    with transaction() as store:
        store.put("access_key", subject, dict(id=subject, label=body.label.strip(), created=utc_now(), revoked=False))
    return {"key": secret}


@router.delete("/api/admin/keys")
def revoke_key(id: str, request: Request):
    admin(request)
    with transaction() as store:
        grant = store.get("access_key", id)
        if not grant:
            raise HTTPException(404, "Access key not found.")
        store.put("access_key", id, {**grant, "revoked": True})
        store.delete("push", id)
    return {"revoked": True}


@router.put("/api/admin/gemini")
def save_gemini(body: Gemini, request: Request):
    admin(request)
    with transaction() as store:
        config = store.get("ai", "gemini", {})
        if body.api_key is not None:
            key = body.api_key.get_secret_value().strip()
            if len(key) < 12 or not key.isascii() or any(not (c.isalnum() or c in "._-") for c in key):
                raise HTTPException(422, "Enter a valid Google AI Studio API key.")
            try:
                config["ciphertext"] = encryption().encrypt(key.encode()).decode()
            except (KeyError, ValueError):
                raise HTTPException(503, "Server credential encryption requires local setup.") from None
        if body.enabled and not config.get("ciphertext"):
            raise HTTPException(422, "Save an API key before enabling Gemini.")
        store.put("ai", "gemini", {**config, "enabled": body.enabled})
    return {"saved": True}


if __name__ == "__main__":
    path = Path(".env")
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if "ADMIN_PASSWORD_HASH" in original or "GOLDSIGNAL_SECRET_KEY" in original:
        raise SystemExit("Admin setup already exists in .env.")
    email = input("Admin email: ").strip().lower()
    if not email or any(c.isspace() or c in "'\"#" for c in email) or "@" not in email:
        raise SystemExit("Enter a valid admin email.")
    password = getpass.getpass("New admin password (at least 14 characters): ")
    if len(password) < 14 or len(password) > 256 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password length or confirmation did not match.")
    salt = secrets.token_hex(16)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"\nADMIN_EMAIL={email}\nADMIN_PASSWORD_HASH={salt}:{password_hash(password, salt)}\n"
                   f"GOLDSIGNAL_SECRET_KEY={Fernet.generate_key().decode()}\n")
    print("Admin password configured. Restart the API and worker.")
