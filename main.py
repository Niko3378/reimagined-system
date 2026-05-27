import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import models
from database import engine, SessionLocal
from routers import auth_router, tickets_router, users_router, notifications_router
import notifications as notif_module
from priority_engine import should_escalate, next_priority

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="HelpDesk IT", version="1.0.0")


async def escalation_loop():
    """Vérifie toutes les heures les tickets à escalader."""
    await asyncio.sleep(10)  # attendre que le serveur soit prêt
    while True:
        db = SessionLocal()
        try:
            tickets = db.query(models.Ticket).filter(
                models.Ticket.status.in_(["ouvert", "en_cours"])
            ).all()
            for ticket in tickets:
                if should_escalate(ticket):
                    old_priority = ticket.priority
                    new_priority = next_priority(old_priority)
                    if new_priority:
                        ticket.priority = new_priority
                        entry = models.TicketHistory(
                            ticket_id=ticket.id,
                            user_id=1,
                            field_changed="priorité (auto)",
                            old_value=old_priority,
                            new_value=new_priority,
                        )
                        db.add(entry)
                        notif_module.broadcaster.broadcast_sync({
                            "type": "ticket_updated",
                            "message": f"Ticket #{ticket.id} escaladé : {old_priority} → {new_priority}",
                            "ticket_id": ticket.id,
                            "by": "système",
                        })
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(3600)  # toutes les heures


@app.on_event("startup")
async def startup():
    notif_module.set_loop(asyncio.get_event_loop())
    asyncio.create_task(escalation_loop())

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(tickets_router.router)
app.include_router(notifications_router.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
