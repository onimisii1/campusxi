"""Supabase Auth: verify the bearer JWT, then load the CampusXI profile and roles."""
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db import get_conn
from app.errors import ApiError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    user_id: UUID
    email: str | None


@lru_cache(maxsize=1)
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def decode_token(token: str) -> dict:
    if settings.supabase_jwt_secret:
        return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"],
                          audience=settings.jwt_audience)
    if not settings.supabase_url:
        raise ApiError(503, "auth_not_configured", "authentication is not configured")
    key = _jwks().get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=settings.jwt_audience)


def current_identity(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Identity:
    if creds is None:
        raise ApiError(401, "unauthenticated", "sign in first")
    try:
        claims = decode_token(creds.credentials)
        return Identity(UUID(claims["sub"]), claims.get("email"))
    except ApiError:
        raise
    except (jwt.PyJWTError, KeyError, ValueError):
        raise ApiError(401, "invalid_token", "your session is invalid or has expired")


def current_user(identity: Identity = Depends(current_identity), conn=Depends(get_conn)) -> dict:
    user = conn.execute("select * from users where id = %s", (identity.user_id,)).fetchone()
    if user is None:
        raise ApiError(403, "profile_required", "complete your CampusXI profile first")
    return user


def require_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if not set(roles) & set(user["roles"]):
            raise ApiError(403, "forbidden", f"requires role: {' or '.join(roles)}")
        return user
    return dependency


require_admin = require_roles("admin", "superadmin")
require_superadmin = require_roles("superadmin")
