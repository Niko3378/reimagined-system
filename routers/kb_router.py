from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import models, schemas, auth
from database import get_db

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

STAFF_ROLES = {"technician", "admin"}


def _get_article_or_404(article_id: int, db: Session) -> models.KBArticle:
    article = db.query(models.KBArticle).filter(models.KBArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return article


@router.get("/", response_model=List[schemas.KBArticleOut])
def list_articles(
    search: Optional[str] = Query(None),
    ticket_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.KBArticle)
    if search:
        q = q.filter(
            models.KBArticle.title.ilike(f"%{search}%") |
            models.KBArticle.content.ilike(f"%{search}%")
        )
    if ticket_type:
        q = q.filter(models.KBArticle.ticket_type == ticket_type)
    if category:
        q = q.filter(models.KBArticle.category == category)
    return q.order_by(models.KBArticle.created_at.desc()).all()


@router.post("/", response_model=schemas.KBArticleOut, status_code=201)
def create_article(
    payload: schemas.KBArticleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux techniciens et admins")
    article = models.KBArticle(**payload.model_dump(), author_id=current_user.id)
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


@router.get("/{article_id}", response_model=schemas.KBArticleOut)
def get_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    article = _get_article_or_404(article_id, db)
    article.views += 1
    db.commit()
    db.refresh(article)
    return article


@router.patch("/{article_id}", response_model=schemas.KBArticleOut)
def update_article(
    article_id: int,
    payload: schemas.KBArticleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    article = _get_article_or_404(article_id, db)
    if current_user.role != "admin" and article.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(article, field, value)
    db.commit()
    db.refresh(article)
    return article


@router.delete("/{article_id}", status_code=204)
def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    article = _get_article_or_404(article_id, db)
    if current_user.role != "admin" and article.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")
    db.delete(article)
    db.commit()
