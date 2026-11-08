"""Read-only views of the activity log and the login log (``logs:read_all``)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.authz import AuthUser, require
from app.db import get_db
from app.models import ActivityLog, Contact, LoginLog, User
from app.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/logs", tags=["logs"])

_USERS = User.__table__  # Core table: the soft-delete filter only touches ORM entities, and a
# person who has since been deleted must still be findable and named in the history.


class ActivityOut(BaseModel):
    id: int
    user_id: int
    username: str
    name: str
    action: str
    resource: str
    resource_id: int | None
    summary: str
    ip: str
    created_at: datetime


class LoginOut(BaseModel):
    id: int
    event: str
    username: str
    user_id: int | None
    ip: str
    created_at: datetime


def _people(db: Session, user_ids: set[int]) -> dict[int, tuple[str, str]]:
    """user id -> (username, display name), deleted people included."""
    if not user_ids:
        return {}
    contacts = Contact.__table__
    rows = db.execute(
        select(_USERS.c.id, _USERS.c.username, contacts.c.name)
        .join(contacts, contacts.c.id == _USERS.c.contact_id)
        .where(_USERS.c.id.in_(user_ids))
    )
    return {r.id: (r.username, r.name) for r in rows}


@router.get("/activity", response_model=Page[ActivityOut])
def list_activity(
    user_id: int | None = None,
    action: str | None = None,
    resource: str | None = None,
    q: str | None = None,
    params: PageParams = Depends(),
    _: AuthUser = Depends(require("logs", "read_all")),
    db: Session = Depends(get_db),
) -> Page[ActivityOut]:
    """What people did, newest first. ``q`` matches the summary or the person's username."""
    stmt = select(ActivityLog)
    if user_id is not None:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if resource:
        stmt = stmt.where(ActivityLog.resource == resource)
    if q:
        by_name = select(_USERS.c.id).where(_USERS.c.username.contains(q, autoescape=True))
        stmt = stmt.where(
            or_(ActivityLog.summary.contains(q, autoescape=True), ActivityLog.user_id.in_(by_name))
        )
    entries, total = paginate(db, stmt, params, ActivityLog.id.desc())
    people = _people(db, {e.user_id for e in entries})
    items = [
        ActivityOut(
            id=e.id, user_id=e.user_id, username=people[e.user_id][0], name=people[e.user_id][1],
            action=e.action, resource=e.resource, resource_id=e.resource_id, summary=e.summary,
            ip=e.ip, created_at=e.created_at,
        )
        for e in entries
    ]  # fmt: skip
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/logins", response_model=Page[LoginOut])
def list_logins(
    user_id: int | None = None,
    event: str | None = None,
    q: str | None = None,
    params: PageParams = Depends(),
    _: AuthUser = Depends(require("logs", "read_all")),
    db: Session = Depends(get_db),
) -> Page[LoginOut]:
    """Sign-in history, newest first. ``q`` matches the username typed or the address."""
    stmt = select(LoginLog)
    if user_id is not None:
        stmt = stmt.where(LoginLog.user_id == user_id)
    if event:
        stmt = stmt.where(LoginLog.event == event)
    if q:
        stmt = stmt.where(
            or_(LoginLog.username.contains(q, autoescape=True), LoginLog.ip.contains(q, autoescape=True))
        )
    entries, total = paginate(db, stmt, params, LoginLog.id.desc())
    return Page(
        items=[LoginOut.model_validate(e, from_attributes=True) for e in entries],
        total=total, page=params.page, page_size=params.page_size,
    )
