"""Dev auth: signed JWTs in a cookie (browser) or Bearer header (services). Permissions come from policy.yaml.

In production the token comes from Entra ID / Okta; only `decode_token` and `load_policy` would change.
"""
import time
from dataclasses import dataclass, field

import jwt
import yaml
from fastapi import Depends, HTTPException, Request

COOKIE = "kyc_session"
ALGO = "HS256"


@dataclass
class User:
    sub: str
    name: str
    roles: list[str]
    permissions: set[str] = field(default_factory=set)
    service: bool = False

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def actor_type(self) -> str:
        return "service" if self.service else "human"


@dataclass
class Policy:
    roles: dict[str, list[str]]
    users: dict[str, dict]

    @classmethod
    def load(cls, path) -> "Policy":
        raw = yaml.safe_load(open(path))
        return cls(raw["roles"], raw["users"])

    def user(self, sub: str) -> User | None:
        u = self.users.get(sub)
        if u is None:
            return None
        perms = {p for r in u.get("roles", []) for p in self.roles.get(r, [])}
        return User(sub, u.get("name", sub), list(u.get("roles", [])), perms, bool(u.get("service")))


def issue_token(secret: str, sub: str, ttl: int = 8 * 3600) -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "iat": now, "exp": now + ttl}, secret, algorithm=ALGO)


def current_user(request: Request) -> User:
    state = request.app.state
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "authentication required")
    try:
        claims = jwt.decode(token, state.settings.jwt_secret, algorithms=[ALGO], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    user = state.policy.user(claims["sub"])
    if user is None:
        raise HTTPException(401, "unknown user")
    request.state.user = user
    return user


def require(permission: str):
    def checker(request: Request, user: User = Depends(current_user)) -> User:
        if not user.can(permission):
            raise HTTPException(403, f"missing permission: {permission}")
        return user
    checker.__name__ = f"require({permission})"
    return checker
