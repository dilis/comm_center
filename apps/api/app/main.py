from fastapi import FastAPI

from app.config import settings
from app.logging_config import configure_logging
from app.routers import auth, contacts, devices, groups, messages, users

configure_logging(settings.log_level)

app = FastAPI(title="Comm Center API")
app.include_router(auth.router)
app.include_router(contacts.router)
app.include_router(devices.router)
app.include_router(groups.router)
app.include_router(messages.router)
app.include_router(users.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
