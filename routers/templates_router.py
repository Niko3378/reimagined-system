from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import models, schemas, auth
from database import get_db

router = APIRouter(prefix="/api/templates", tags=["templates"])

STAFF_ROLES = {"technician", "admin"}


def _get_or_404(template_id: int, db: Session) -> models.TicketTemplate:
    t = db.query(models.TicketTemplate).filter(models.TicketTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    return t


@router.get("/", response_model=List[schemas.TicketTemplateOut])
def list_templates(
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.TicketTemplate)
    if search:
        q = q.filter(
            models.TicketTemplate.name.ilike(f"%{search}%") |
            models.TicketTemplate.title.ilike(f"%{search}%")
        )
    if type:
        q = q.filter(models.TicketTemplate.type == type)
    if category:
        q = q.filter(models.TicketTemplate.category == category)
    return q.order_by(models.TicketTemplate.usage_count.desc(), models.TicketTemplate.name).all()


@router.post("/", response_model=schemas.TicketTemplateOut, status_code=201)
def create_template(
    payload: schemas.TicketTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux techniciens et admins")
    template = models.TicketTemplate(**payload.model_dump(), author_id=current_user.id)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/use", response_model=schemas.TicketTemplateOut)
def use_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    template = _get_or_404(template_id, db)
    template.usage_count += 1
    db.commit()
    db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=schemas.TicketTemplateOut)
def update_template(
    template_id: int,
    payload: schemas.TicketTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    template = _get_or_404(template_id, db)
    if current_user.role != "admin" and template.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    template = _get_or_404(template_id, db)
    if current_user.role != "admin" and template.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")
    db.delete(template)
    db.commit()
