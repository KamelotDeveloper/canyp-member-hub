"""Authentication utilities: bcrypt hashing, JWT tokens, FastAPI dependency."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config import settings
from backend.database import get_db
from backend.models.usuario import Usuario

ALGORITHM = settings.JWT_ALGORITHM
EXPIRATION_MINUTES = settings.JWT_EXPIRATION_MINUTES
SECRET_KEY = settings.JWT_SECRET or secrets.token_urlsafe(48)

_bearer = HTTPBearer(auto_error=False)

# Valid bcrypt hash used to keep response time constant on unknown-user logins.
_DUMMY_HASH = bcrypt.hashpw(b"canyp-dummy", bcrypt.gensalt()).decode("utf-8")


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (raw bytes, no passlib)."""
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))


def create_access_token(user_id: str, username: str) -> str:
    """Create a JWT access token with sub, username, iat, exp claims."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=EXPIRATION_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db=Depends(get_db),
) -> Usuario:
    """FastAPI dependency: extract and validate the current user from Bearer token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        payload = jwt.decode(
            credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

    user = db.get(Usuario, payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    return user
