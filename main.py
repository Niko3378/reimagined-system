import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import models
from database import engine
from routers import auth_router, tickets_router, users_router, notifications_router
import notifications as notif_module

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="HelpDesk IT", version="1.0.0")


@app.on_event("startup")
async def startup():
    notif_module.set_loop(asyncio.get_event_loop())

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(tickets_router.router)
app.include_router(notifications_router.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
