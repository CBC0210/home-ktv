"""Small, bounded single-worker request guards for the event server."""
import re
import time
import threading
import logging
from collections import OrderedDict, deque

from fastapi import Request
from starlette.responses import JSONResponse
from .config import settings

_windows = OrderedDict()
_lock = threading.Lock()
_LAN = re.compile(r"^https?://(localhost|127\.0\.0\.1|(?:10|127)(?:\.\d{1,3}){3}|(?:192\.168|169\.254)(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|[A-Za-z0-9-]+\.local)(:\d+)?$")


def origin_allowed(origin: str) -> bool:
    return origin.rstrip("/") == settings.public_base_url.rstrip("/") or bool(_LAN.fullmatch(origin))


def allow_request(key: tuple, limit: int, seconds: int, *, record: bool = True) -> bool:
    now = time.monotonic()
    with _lock:
        hits = _windows.setdefault(key, deque())
        _windows.move_to_end(key)
        while hits and hits[0] <= now - seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        if record:
            hits.append(now)
        while len(_windows) > 10000:
            _windows.popitem(last=False)
        return True


async def security_guard(request: Request, call_next):
    path = request.url.path
    mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    if mutation:
        origin = request.headers.get("origin")
        if origin and not origin_allowed(origin):
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        # Bound streamed/chunked bodies too, before JSON parsing/validation.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        request._body = bytes(body)
    password_attempt = mutation and (path in {"/api/guests/join", "/api/auth/admin/login", "/api/auth/admin/password"}
                                    or path.endswith(("/admin/verify", "/player-session")))
    key = ("auth-failure", request.client.host if request.client else "unknown")
    if password_attempt and not allow_request(key, 30, 300, record=False):
        return JSONResponse({"detail": "Too many failed attempts; try again shortly"}, status_code=429,
                            headers={"Retry-After": "300"})
    response = await call_next(request)
    if password_attempt and response.status_code in (400, 401, 403, 422):
        allow_request(key, 30, 300)
    return response


class RedactSessionTokens(logging.Filter):
    def filter(self, record):
        def redact(value):
            if isinstance(value, str):
                return re.sub(r"([?&]token=)[^&\s\"']+", r"\1[redacted]", value)
            return value
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) for k, v in record.args.items()}
        return True
