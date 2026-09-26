"""Authentication endpoints: login, logout, status, first-user bootstrap."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.usuario import Usuario
from backend.security import (
    _DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ──────────────────────────────────────────────────────────────

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str
    password: str  # NO min_length — avoids 401-vs-422 oracle


class FirstUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6, max_length=128)


class UserResponse(BaseSchema):
    id: str
    username: str
    created_at: datetime


class TokenResponse(BaseModel):
    token: str


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token.

    Both wrong-password and unknown-user yield an identical 401 response
    with a dummy bcrypt verify on unknown users to blunt timing oracles.
    """
    user = db.query(Usuario).filter(Usuario.username == body.username).first()
    if user is None:
        # Dummy verify to keep response time constant
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token(user.id, user.username)
    return {"token": token}


@router.post("/logout")
def logout():
    """Client-side logout — server is stateless, always returns 200."""
    return {"status": "ok"}


@router.get("/status")
def status_check(db: Session = Depends(get_db)):
    """Check whether any users exist in the system (open, no auth)."""
    count = db.query(Usuario).count()
    return {"users_exist": count > 0}


@router.post("/first-user", status_code=status.HTTP_201_CREATED)
def first_user(body: FirstUserRequest, db: Session = Depends(get_db)):
    """Create the first user when no users exist.

    Returns 409 if users already exist, or if a race condition causes a
    UNIQUE constraint violation on username.
    """
    count = db.query(Usuario).count()
    if count > 0:
        raise HTTPException(
            status_code=409, detail="Ya existe un usuario en el sistema"
        )

    user = Usuario(
        username=body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="El nombre de usuario ya existe"
        )
    db.refresh(user)

    token = create_access_token(user.id, user.username)
    return {"token": token, "user": UserResponse.model_validate(user)}
