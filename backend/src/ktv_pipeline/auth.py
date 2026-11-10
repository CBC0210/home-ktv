"""Authentication utilities — bcrypt hashing, JWT sessions, room/admin auth."""
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import hmac
from fastapi import HTTPException, Request
from jose import JWTError, jwt

from ktv_pipeline.config import settings

# ── JWT settings ──────────────────────────────────────────────────────────────
ALGORITHM = "HS256"
# Home-KTV guests return every few weeks; a 7-day TTL meant every phone's
# stored session was dead by the next party (WS handshakes 403'd forever).
# 60 days + client-side expiry detection keeps re-joins rare but bounded.
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 60  # 60 days


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(
    guest_id: str,
    room_id: str,
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
    scope: Optional[str] = None,
) -> str:
    """Create a signed JWT for a guest session."""
    scope = scope or ("system_admin" if is_admin and room_id == "__admin__" else "room_admin" if is_admin else "guest")
    if expires_delta is None:
        expires_delta = timedelta(hours=12 if is_admin else ACCESS_TOKEN_EXPIRE_HOURS)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": guest_id,
        "room_id": room_id,
        "is_admin": is_admin,
        "scope": scope,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.admin_cookie_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.admin_cookie_secret, algorithms=[ALGORITHM],
                             options={"require_exp": True, "require_sub": True, "require_iat": True})
        if not isinstance(payload.get("sub"), str) or not isinstance(payload.get("room_id"), str):
            raise HTTPException(status_code=401, detail="Invalid session")
        # Old elevated sessions lack a trustworthy privilege scope. Guests
        # remain compatible; administrators must verify their password again.
        if payload.get("is_admin") and payload.get("scope") not in ("system_admin", "room_admin"):
            raise HTTPException(status_code=401, detail="Please sign in again")
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
    return hmac.compare_digest(provided_password.encode(), settings.admin_password.encode())

def is_system_admin(payload: dict) -> bool:
    return bool(payload.get("is_admin") and payload.get("scope") == "system_admin"
                and payload.get("room_id") == "__admin__")


def is_room_admin(payload: dict, room_id: str) -> bool:
    return is_system_admin(payload) or bool(
        payload.get("is_admin") and payload.get("scope") == "room_admin"
        and payload.get("room_id") == room_id
    )


def ensure_room_access(payload: dict, room_id: str) -> None:
    if not is_system_admin(payload) and payload.get("room_id") != room_id:
        raise HTTPException(status_code=403, detail="Join this room first")
