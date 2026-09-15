"""Usuario CRUD endpoints: list, create, delete (last-user guarded).

All routes require authentication — the router-level guard is applied at
include time in ``backend/main.py`` (design D8). Every user is equal (D1),
so any authenticated user may list/create/delete usuarios, except that the
last remaining user can never be deleted.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.usuario import Usuario
from backend.routers.auth import BaseSchema
from backend.security import hash_password

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])


# ── Schemas ──────────────────────────────────────────────────────────────

class UsuarioResponse(BaseSchema):
    id: str
    username: str
    created_at: datetime


class UsuarioCreate(BaseSchema):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6, max_length=128)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=list[UsuarioResponse])
def list_usuarios(db: Session = Depends(get_db)):
    """List all users (id, username, created_at — never password_hash)."""
    return db.query(Usuario).order_by(Usuario.created_at).all()


@router.post("", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def create_usuario(data: UsuarioCreate, db: Session = Depends(get_db)):
    """Create a new user.

    Returns 409 on duplicate username (UNIQUE violation) and 422 when the
    password is shorter than 6 characters (pydantic validation).
    """
    user = Usuario(
        username=data.username,
        password_hash=hash_password(data.password),
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
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_usuario(user_id: str, db: Session = Depends(get_db)):
    """Delete a user, refusing to delete the last remaining user.

    Returns 404 for an unknown id and 409 when deleting would leave the
    system with no users at all.
    """
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=404, detail=f"Usuario {user_id} no encontrado"
        )

    count = db.query(Usuario).count()
    if count <= 1:
        raise HTTPException(
            status_code=409, detail="No se puede eliminar el último usuario"
        )

    db.delete(user)
    db.commit()
