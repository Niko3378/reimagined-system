from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import models, schemas, auth
from database import get_db

router = APIRouter(tags=["processes"])

STAFF_ROLES = {"technician", "admin"}
TASK_STATUSES = {"en_attente", "en_cours", "fait"}


# ─── Process Templates ────────────────────────────────────────────────────────

tpl_router = APIRouter(prefix="/api/process-templates")


@tpl_router.get("/", response_model=List[schemas.ProcessTemplateOut])
def list_process_templates(
    ticket_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.ProcessTemplate)
    if ticket_type:
        q = q.filter(models.ProcessTemplate.ticket_type == ticket_type)
    return q.order_by(models.ProcessTemplate.name).all()


@tpl_router.post("/", response_model=schemas.ProcessTemplateOut, status_code=201)
def create_process_template(
    payload: schemas.ProcessTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux techniciens et admins")
    tpl = models.ProcessTemplate(
        name=payload.name,
        description=payload.description,
        ticket_type=payload.ticket_type,
        author_id=current_user.id,
    )
    db.add(tpl)
    db.flush()
    for s in payload.steps:
        db.add(models.ProcessTemplateStep(
            template_id=tpl.id, order=s.order, name=s.name, description=s.description
        ))
    db.commit()
    db.refresh(tpl)
    return tpl


@tpl_router.get("/{tpl_id}", response_model=schemas.ProcessTemplateOut)
def get_process_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tpl = db.query(models.ProcessTemplate).filter(models.ProcessTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Modèle de processus introuvable")
    return tpl


@tpl_router.patch("/{tpl_id}", response_model=schemas.ProcessTemplateOut)
def update_process_template(
    tpl_id: int,
    payload: schemas.ProcessTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tpl = db.query(models.ProcessTemplate).filter(models.ProcessTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Modèle de processus introuvable")
    if current_user.role != "admin" and tpl.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")
    if payload.name is not None:
        tpl.name = payload.name
    if payload.description is not None:
        tpl.description = payload.description
    if payload.ticket_type is not None:
        tpl.ticket_type = payload.ticket_type
    if payload.steps is not None:
        for step in tpl.steps:
            db.delete(step)
        db.flush()
        for s in payload.steps:
            db.add(models.ProcessTemplateStep(
                template_id=tpl.id, order=s.order, name=s.name, description=s.description
            ))
    db.commit()
    db.refresh(tpl)
    return tpl


@tpl_router.delete("/{tpl_id}", status_code=204)
def delete_process_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tpl = db.query(models.ProcessTemplate).filter(models.ProcessTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Modèle de processus introuvable")
    if current_user.role != "admin" and tpl.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")
    db.delete(tpl)
    db.commit()


# ─── Ticket Process ───────────────────────────────────────────────────────────

ticket_process_router = APIRouter(prefix="/api/tickets")


@ticket_process_router.post("/{ticket_id}/process", response_model=schemas.TicketProcessOut, status_code=201)
def attach_process(
    ticket_id: int,
    payload: schemas.AttachProcessPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux techniciens et admins")
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    existing = db.query(models.TicketProcess).filter(models.TicketProcess.ticket_id == ticket_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Un processus est déjà attaché à ce ticket")

    if payload.template_id:
        tpl = db.query(models.ProcessTemplate).filter(models.ProcessTemplate.id == payload.template_id).first()
        if not tpl:
            raise HTTPException(status_code=404, detail="Modèle de processus introuvable")
        name = tpl.name
        steps = tpl.steps
    elif payload.name and payload.steps:
        name = payload.name
        steps = payload.steps
    else:
        raise HTTPException(status_code=400, detail="Fournissez template_id ou name+steps")

    process = models.TicketProcess(ticket_id=ticket_id, name=name)
    db.add(process)
    db.flush()
    for s in steps:
        db.add(models.TicketProcessTask(
            process_id=process.id,
            order=s.order if hasattr(s, 'order') else s['order'],
            name=s.name if hasattr(s, 'name') else s['name'],
            description=s.description if hasattr(s, 'description') else s.get('description'),
        ))
    db.commit()
    db.refresh(process)
    return process


@ticket_process_router.get("/{ticket_id}/process", response_model=schemas.TicketProcessOut)
def get_ticket_process(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    process = db.query(models.TicketProcess).filter(models.TicketProcess.ticket_id == ticket_id).first()
    if not process:
        raise HTTPException(status_code=404, detail="Aucun processus attaché à ce ticket")
    return process


@ticket_process_router.delete("/{ticket_id}/process", status_code=204)
def detach_process(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux techniciens et admins")
    process = db.query(models.TicketProcess).filter(models.TicketProcess.ticket_id == ticket_id).first()
    if not process:
        raise HTTPException(status_code=404, detail="Aucun processus attaché à ce ticket")
    db.delete(process)
    db.commit()


# ─── Process Tasks ────────────────────────────────────────────────────────────

task_router = APIRouter(prefix="/api/process-tasks")


@task_router.patch("/{task_id}", response_model=schemas.TicketProcessTaskOut)
def update_task(
    task_id: int,
    payload: schemas.UpdateTaskPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux techniciens et admins")
    task = db.query(models.TicketProcessTask).filter(models.TicketProcessTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    if payload.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Statut invalide")

    # Enforce sequential dependency
    if payload.status in ("en_cours", "fait") and task.order > 1:
        prev = db.query(models.TicketProcessTask).filter(
            models.TicketProcessTask.process_id == task.process_id,
            models.TicketProcessTask.order == task.order - 1,
        ).first()
        if prev and prev.status != "fait":
            raise HTTPException(
                status_code=400,
                detail=f"La tâche précédente « {prev.name} » doit être terminée d'abord"
            )

    task.status = payload.status
    if payload.assigned_to_id is not None:
        task.assigned_to_id = payload.assigned_to_id
    if payload.status == "fait":
        task.completed_at = datetime.utcnow()
        task.completed_by_id = current_user.id
    elif task.status != "fait":
        task.completed_at = None
        task.completed_by_id = None

    db.commit()
    db.refresh(task)
    return task


# Register all sub-routers onto main router
router.include_router(tpl_router)
router.include_router(ticket_process_router)
router.include_router(task_router)
