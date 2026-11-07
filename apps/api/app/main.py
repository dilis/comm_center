from fastapi import FastAPI

from app.routers import auth, contacts, groups, users

app = FastAPI(title="Comm Center API")
app.include_router(auth.router)
app.include_router(contacts.router)
app.include_router(groups.router)
app.include_router(users.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
