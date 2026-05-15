"""Authentication utilities — bcrypt hashing, JWT sessions, room/admin auth."""
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request
from jose import JWTError, jwt

from ktv_pipeline.config import settings

# ── JWT settings ──────────────────────────────────────────────────────────────
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 1 week


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(
    guest_id: str,
    room_id: str,
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT for a guest session."""
    if expires_delta is None:
        expires_delta = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": guest_id,
        "room_id": room_id,
        "is_admin": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.admin_cookie_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.admin_cookie_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired session: {exc}")


def guest_from_request(request: Request) -> dict:
    """Extract guest session from request cookies or Authorization header.
    
    Looks for `ktv_session` cookie first, then `Authorization: Bearer <token>`.
    Returns the JWT payload dict.
    Raises 401 if missing or invalid.
    """
    token: Optional[str] = None

    # Authorization header takes priority — an explicit Bearer token is a
    # deliberate choice (e.g. the admin page) and must NOT be shadowed by a
    # leftover guest `ktv_session` cookie from a prior Remote session.
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.cookies.get("ktv_session")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated — no session token")

    return decode_access_token(token)


def get_optional_guest(request: Request) -> Optional[dict]:
    """Like guest_from_request but returns None instead of raising 401."""
    try:
        return guest_from_request(request)
    except HTTPException:
        return None


# ── Room password verification ───────────────────────────────────────────────
def verify_room_password(room_password_hash: Optional[str], provided_password: str) -> bool:
    """Check if provided password matches the room's bcrypt hash.
    
    If room has no password (None/empty), always returns True.
    """
    if not room_password_hash:
        return True
    return verify_password(provided_password, room_password_hash)


def verify_admin_password(provided_password: str) -> bool:
    """Check if provided password matches the admin password from settings."""
    return provided_password == settings.admin_password