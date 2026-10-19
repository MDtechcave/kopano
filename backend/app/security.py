"""Passwords, login tokens, and the 'who is calling?' checks."""
import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import config
from app.database import ROLE_CLIENT, ROLE_SALES, User, get_db, utc_now

# auto_error=False lets us decide ourselves what to do when there is no token.
bearer_scheme = HTTPBearer(auto_error=False)

HASH_ROUNDS = 200_000


def hash_password(password: str) -> str:
    """Store passwords as salt + slow hash. We never keep the real password."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ROUNDS)
    return f"{salt}${digest.hex()}"


def check_password(password: str, stored_hash: str) -> bool:
    salt, expected = stored_hash.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ROUNDS)
    return hmac.compare_digest(digest.hex(), expected)


def generate_temporary_password() -> str:
    """A random password for a new or reset staff account. They must change it at first sign-in."""
    return secrets.token_urlsafe(9)


def create_token(user: User) -> str:
    """The token only says WHO the user is. Their role is looked up in the database
    on every request, so a token can never be used to claim a different role."""
    payload = {"sub": str(user.id), "exp": utc_now() + timedelta(hours=config.TOKEN_LIFETIME_HOURS)}
    return jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")


def _user_from_token(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
        return db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """For public pages that show a little more to signed-in users."""
    if credentials is None:
        return None
    return _user_from_token(credentials.credentials, db)


def get_signed_in_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Everything private starts here. 401 means 'sign in (again)'; the X-Auth-Error
    header lets the website tell an expired session apart from never having signed in."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.", headers={"X-Auth-Error": "signed_out"})
    try:
        payload = jwt.decode(credentials.credentials, config.SECRET_KEY, algorithms=["HS256"])
        user = db.get(User, int(payload["sub"]))
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Your session has expired. Please sign in again.",
            headers={"X-Auth-Error": "session_expired"},
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.", headers={"X-Auth-Error": "signed_out"})
    if not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This account has been deactivated.", headers={"X-Auth-Error": "deactivated"}
        )
    return user


def get_current_user(user: User = Depends(get_signed_in_user)) -> User:
    """Like get_signed_in_user, but a person on a temporary password can do nothing except
    change it (the change-password and /me endpoints use get_signed_in_user instead)."""
    if user.must_change_password:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Please choose a new password first.",
            headers={"X-Auth-Error": "password_change_required"},
        )
    return user


def require_sales(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_SALES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This area is for the sales team.")
    return user


def require_client(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_CLIENT or user.company_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This area is for client accounts.")
    return user


def require_admin(user: User = Depends(require_sales)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can manage the sales team.")
    return user
