"""Login, tokens and the bootstrap admin ([C4] /api/auth/*, ticket D7).

Passwords are argon2id hashes - not because bcrypt would fail an audit, but because the memory
cost is what makes an offline attack on a stolen dump expensive, and a police credential database
is exactly the dump somebody would steal.

Two tokens, deliberately different lifetimes: an access token good for 15 minutes and a refresh
token good for 8 hours - one shift. A stolen access token expires before the shift it was stolen
in ends; a refresh token dies with the shift. Both are signed with JWT_SECRET, and when that is
unset the module signs with a random per-process key rather than trusting unsigned tokens: "no
secret configured" must never mean "everything is valid".

Bootstrap:

    python services/api/auth.py bootstrap --username admin --role SYSTEM_ADMIN

The password is read from PRAHARI_BOOTSTRAP_PASSWORD or prompted for; it is never taken from a
command-line argument, because that lands in shell history and in `ps`.
"""

import argparse
import getpass
import logging
import os
import secrets
import sys
import time
from pathlib import Path

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scope import ROLES, SYSTEM_ADMIN, Scope   # noqa: E402

log = logging.getLogger("auth")

ACCESS_TTL_S = 15 * 60            # one interruption, not one shift
REFRESH_TTL_S = 8 * 3600          # one shift
ALGORITHM = "HS256"


class AuthError(Exception):
    """Wrong credentials, an expired token, a disabled account. Deliberately one exception:
    telling the caller *which* of those it was is how an attacker enumerates usernames."""

    status_code = 401


def secret():
    configured = os.environ.get("JWT_SECRET")
    if configured:
        return configured
    if not hasattr(secret, "_dev"):
        secret._dev = secrets.token_urlsafe(32)
        log.warning("JWT_SECRET is unset - signing with a random per-process key (dev only)")
    return secret._dev


def _hasher():
    from argon2 import PasswordHasher
    return PasswordHasher()


def hash_password(password):
    if not password or len(password) < 8:
        raise ValueError("a password shorter than 8 characters is not a password")
    return _hasher().hash(password)


def verify_password(stored_hash, password):
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
    try:
        return _hasher().verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _dummy_hash():
    """A real argon2 hash of a value nobody knows, computed once.

    Verifying against it costs the same as verifying a real one, which is the point:
    returning instantly for an unknown username is a timing oracle that tells an attacker
    which accounts exist.
    """
    if not hasattr(_dummy_hash, "_value"):
        _dummy_hash._value = _hasher().hash(secrets.token_urlsafe(32))
    return _dummy_hash._value


def issue_tokens(user):
    """Access + refresh for one user row."""
    now = int(time.time())
    base = {"sub": str(user["id"]), "role": user["role"], "dept_id": user["dept_id"],
            "district_code": user["district_code"], "iat": now}
    access = jwt.encode({**base, "typ": "access", "exp": now + ACCESS_TTL_S},
                        secret(), algorithm=ALGORITHM)
    refresh = jwt.encode({**base, "typ": "refresh", "exp": now + REFRESH_TTL_S},
                         secret(), algorithm=ALGORITHM)
    return {"access": access, "refresh": refresh,
            "role": user["role"], "dept": user["dept_id"]}


def scope_from_token(token, expect="access"):
    """Decode a token into a Scope, or raise AuthError. Never trust a claim we did not sign."""
    try:
        claims = jwt.decode(token, secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    if expect and claims.get("typ") != expect:
        # A refresh token is not an access token. Accepting one where the other is expected
        # turns an 8-hour credential into a 15-minute one's privileges.
        raise AuthError(f"expected a {expect} token")
    return Scope(user_id=claims.get("sub"), role=(claims.get("role") or "").upper(),
                 dept_id=claims.get("dept_id"), district_code=claims.get("district_code"))


class UserRepo:
    def __init__(self, store):
        self.store = store

    def create(self, username, password, role, dept_id=None, district_code=None):
        if role.upper() not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO users (username, pw_hash, dept_id, district_code, role)
                           VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                        (username, hash_password(password), dept_id, district_code, role.upper()))
            return cur.fetchone()[0]

    def get(self, username):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, username, pw_hash, dept_id, district_code, role, active
                           FROM users WHERE username = %s""", (username,))
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([c.name for c in cur.description], row))

    def authenticate(self, username, password):
        user = self.get(username)
        if user is None:
            verify_password(_dummy_hash(), password or "")
            raise AuthError("invalid credentials")
        if not user["active"]:
            raise AuthError("invalid credentials")
        if not verify_password(user["pw_hash"], password or ""):
            raise AuthError("invalid credentials")
        return user


def build_router(store):
    """[C4]: POST /api/auth/login and /api/auth/refresh."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/auth")
    users = UserRepo(store)

    class LoginBody(BaseModel):
        username: str
        password: str

    class RefreshBody(BaseModel):
        refresh: str

    @router.post("/login")
    def login(body: LoginBody):
        try:
            user = users.authenticate(body.username, body.password)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="invalid credentials") from exc
        return issue_tokens(user)

    @router.post("/refresh")
    def refresh(body: RefreshBody):
        try:
            scope = scope_from_token(body.refresh, expect="refresh")
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="invalid refresh token") from exc
        user = {"id": scope.user_id, "role": scope.role, "dept_id": scope.dept_id,
                "district_code": scope.district_code}
        return {"access": issue_tokens(user)["access"]}

    return router


def current_scope():
    """FastAPI dependency factory: Authorization: Bearer <access token> -> Scope."""
    from fastapi import Header, HTTPException

    def dependency(authorization: str = Header(None)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            return scope_from_token(authorization.split(" ", 1)[1])
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    return dependency


def requires(capability):
    """Dependency factory: 403 unless the scope holds the capability ([C10])."""
    from fastapi import Depends, HTTPException

    def dependency(scope=Depends(current_scope())):
        if not scope.can(capability):
            raise HTTPException(status_code=403,
                                detail=f"role {scope.role} does not hold {capability}")
        return scope

    return dependency


def _bootstrap(args):
    from store import Store

    password = os.environ.get("PRAHARI_BOOTSTRAP_PASSWORD")
    if not password:
        password = getpass.getpass("password for the bootstrap admin: ")
    store = Store(dsn=args.dsn)
    repo = UserRepo(store)
    if repo.get(args.username):
        print(f"user {args.username} already exists - nothing to do")
        return 0
    user_id = repo.create(args.username, password, args.role,
                          dept_id=args.dept_id, district_code=args.district)
    print(f"created {args.role} {args.username} (id {user_id})")
    if args.role.upper() == SYSTEM_ADMIN:
        print("note: per [C10] this account administers the system and cannot view video")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap", help="create the first administrator")
    boot.add_argument("--username", required=True)
    boot.add_argument("--role", default=SYSTEM_ADMIN, choices=sorted(ROLES))
    boot.add_argument("--dept-id", type=int, default=None, dest="dept_id")
    boot.add_argument("--district", default=None)
    boot.add_argument("--dsn", default=None)
    args = ap.parse_args()
    return _bootstrap(args)


if __name__ == "__main__":
    sys.exit(main())
