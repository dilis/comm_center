from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authz import AuthUser, require, scope
from app.clock import utcnow
from app.db import get_db
from app.deps import get_current_user
from app.messaging import Direction, derive_direction, inbound_agent_ids
from app.models import Contact, ContactPhone, GsmDevice, Message, User
from app.pagination import Page, PageParams, paginate
from app.phones import normalize_e164
from app.schemas import SortOrder

router = APIRouter(prefix="/messages", tags=["messages"])

MAX_CONTENT_LENGTH = 1600  # ten concatenated SMS segments
Status = Literal["queued", "sending", "sent", "failed", "delivered", "received"]


class MessageOut(BaseModel):
    id: int
    channel: str
    direction: Direction  # computed from the owner, never stored
    contact_id: int
    contact_name: str
    phone_number: str  # E.164 snapshot, set once
    content: str  # untrusted text: clients must escape it
    status: Status
    owner_id: int
    gsm_device_id: int | None
    created_at: datetime
    sent_at: datetime | None
    received_at: datetime | None
    error_message: str | None


class SendRequest(BaseModel):
    contact_id: int
    content: str = Field(max_length=MAX_CONTENT_LENGTH)
    phone: str | None = None  # one of the contact's numbers; default: primary, else first

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value

    @field_validator("phone")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        return None if value is None else normalize_e164(value)


class Counts(BaseModel):
    all: int
    sent: int
    received: int


def to_out(db: Session, messages: list[Message]) -> list[MessageOut]:
    if not messages:
        return []
    # Owners and contacts may be soft-deleted while their messages remain, so include them.
    keep = {"include_deleted": True}
    owners = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.id.in_({m.owner_id for m in messages})), execution_options=keep
        )
    }
    names = dict(
        db.execute(
            select(Contact.id, Contact.name).where(
                Contact.id.in_({m.contact_id for m in messages})
            ),
            execution_options=keep,
        ).all()
    )
    device_by_agent = dict(
        db.execute(
            select(GsmDevice.agent_user_id, GsmDevice.id).where(
                GsmDevice.agent_user_id.in_({m.owner_id for m in messages})
            ),
            execution_options=keep,
        ).all()
    )
    out = []
    for m in messages:
        owner = owners[m.owner_id]
        direction = derive_direction(owner.is_system, owner.agent_direction)
        out.append(
            MessageOut(
                id=m.id, channel=m.channel, direction=direction, contact_id=m.contact_id,
                contact_name=names[m.contact_id], phone_number=m.phone_number, content=m.content,
                status=m.status, owner_id=m.owner_id,
                # stored for outbound only; for inbound it follows from the receiving agent
                gsm_device_id=device_by_agent.get(m.owner_id) if direction == "inbound" else m.gsm_device_id,
                created_at=m.created_at, sent_at=m.sent_at, received_at=m.received_at,
                error_message=m.error_message,
            )
        )  # fmt: skip
    return out


def get_scoped(db: Session, caller: AuthUser, message_id: int) -> Message:
    """A message the caller may read (and so delete); 404 otherwise."""
    stmt = scope(select(Message).where(Message.id == message_id), caller, "messages")
    message = db.scalars(stmt).one_or_none()
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    return message


def by_direction(stmt, direction: Literal["all", "sent", "received"]):
    if direction == "received":
        return stmt.where(Message.owner_id.in_(inbound_agent_ids()))
    if direction == "sent":
        return stmt.where(Message.owner_id.not_in(inbound_agent_ids()))
    return stmt


@router.get("", response_model=Page[MessageOut])
def list_messages(
    direction: Literal["all", "sent", "received"] = "all",
    status: Status | None = None,
    contact_id: int | None = None,
    q: str | None = None,
    order: SortOrder = "desc",
    params: PageParams = Depends(),
    caller: AuthUser = Depends(get_current_user),  # scope() answers 403 without read access
    db: Session = Depends(get_db),
) -> Page[MessageOut]:
    stmt = by_direction(scope(select(Message), caller, "messages"), direction)
    if status:
        stmt = stmt.where(Message.status == status)
    if contact_id is not None:
        stmt = stmt.where(Message.contact_id == contact_id)
    if q:
        stmt = stmt.where(
            Message.content.contains(q, autoescape=True)
            | Message.phone_number.contains(q, autoescape=True)
        )
    column = Message.created_at.desc() if order == "desc" else Message.created_at.asc()
    id_column = Message.id.desc() if order == "desc" else Message.id.asc()
    messages, total = paginate(db, stmt, params, column, id_column)
    return Page(
        items=to_out(db, messages), total=total, page=params.page, page_size=params.page_size
    )


@router.get("/counts", response_model=Counts)
def message_counts(
    caller: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> Counts:
    """Badge numbers for the All / Sent / Received tabs, under the caller's read scope."""
    base = scope(select(Message.id), caller, "messages")

    def count(direction: Literal["all", "sent", "received"]) -> int:
        stmt = by_direction(base, direction)
        return db.scalar(select(func.count()).select_from(stmt.subquery()))

    return Counts(all=count("all"), sent=count("sent"), received=count("received"))


@router.post("/send", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def send_message(
    body: SendRequest,
    caller: AuthUser = Depends(require("messages", "create")),
    db: Session = Depends(get_db),
) -> MessageOut:
    """Queue a message for the GSM worker. The caller owns it, which makes it outbound."""
    contact = db.scalars(
        scope(select(Contact).where(Contact.id == body.contact_id), caller, "contacts")
    ).one_or_none()
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    phones = db.scalars(
        select(ContactPhone).where(ContactPhone.contact_id == contact.id).order_by(ContactPhone.id)
    ).all()
    if body.phone is not None:
        chosen = next((p for p in phones if p.phone_e164 == body.phone), None)
        if chosen is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "phone is not the contact's")
    else:
        chosen = next((p for p in phones if p.is_primary), phones[0] if phones else None)
        if chosen is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "contact has no phone number"
            )
    message = Message(
        channel="gsm", contact_id=contact.id, phone_number=chosen.phone_e164,
        content=body.content, status="queued", owner_id=caller.id,
    )  # fmt: skip
    db.add(message)
    db.commit()
    return to_out(db, [message])[0]


@router.get("/{message_id}", response_model=MessageOut)
def read_message(
    message_id: int, caller: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> MessageOut:
    return to_out(db, [get_scoped(db, caller, message_id)])[0]


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    message_id: int,
    caller: AuthUser = Depends(require("messages", "delete")),
    db: Session = Depends(get_db),
) -> Response:
    get_scoped(db, caller, message_id).deleted_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
