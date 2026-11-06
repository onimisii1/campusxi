"""Request IDs with structured (JSON) access logs, and a small in-process rate limiter for money,
ID-check and stake routes. No extra libraries."""
import hashlib
import json
import logging
import threading
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = logging.getLogger("campusxi.http")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"t": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage()}
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging():
    root = logging.getLogger("campusxi")
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
        root.setLevel(logging.INFO)


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info("request", extra={"fields": {
            "rid": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1)}})
        return response


# (path prefix, methods, requests per minute)
LIMITS = [
    ("/wallet/", {"POST"}, 20),
    ("/me/kyc", {"POST"}, 5),
    ("/me/bank-accounts", {"POST"}, 10),
    ("/bets", {"POST"}, 30),
    ("/contests/", {"POST"}, 30),
]


class RateLimit(BaseHTTPMiddleware):
    """Token bucket per (caller, rule). Webhooks are never limited."""

    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict = {}
        self._lock = threading.Lock()

    async def dispatch(self, request, call_next):
        from app.config import settings
        if not settings.rate_limit_enabled:
            return await call_next(request)
        path = request.url.path
        rule = next((r for r in LIMITS if path.startswith(r[0]) and request.method in r[1]), None)
        if rule and not path.startswith("/payments/"):
            who = request.headers.get("authorization") or (request.client.host if request.client else "?")
            key = (hashlib.sha256(who.encode()).hexdigest()[:16], rule[0])
            if not self._take(key, rule[2]):
                return JSONResponse({"error": {"code": "rate_limited",
                                               "message": "too many requests; wait a moment and try again"}},
                                    status_code=429, headers={"Retry-After": "10"})
        return await call_next(request)

    def _take(self, key, per_minute: int) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (per_minute, now))
            tokens = min(per_minute, tokens + (now - last) * per_minute / 60)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True
