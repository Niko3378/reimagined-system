from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models
import schemas
import auth
from database import get_db

router = APIRouter(prefix="/api/users", tags=["users"])

VALID_ROLES = {"user", "technician", "admin"}


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@router.get("/staff", response_model=List[schemas.UserOut])
def list_staff(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return db.query(models.User).filter(
        models.User.role.in_(["technician", "admin"])
    ).order_by(models.User.username).all()


@router.get("/", response_model=List[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    return db.query(models.User).order_by(models.User.username).all()


@router.patch("/{user_id}/role", response_model=schemas.UserOut)
def update_role(
    user_id: int,
    role_in: schemas.RoleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if role_in.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {VALID_ROLES}")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.role = role_in.role
    db.commit()
    db.refresh(user)
    return user
