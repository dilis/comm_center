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
from app.templating import UnknownPlaceholders, render, validate

router = APIRouter(prefix="/messages", tags=["messages"])

MAX_CONTENT_LENGTH = 1600  # ten concatenated SMS segments
MAX_BULK_RECIPIENTS = 500
TOO_LONG_WITH_NAME = "message too long once the name is inserted"
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


class ContentRequest(BaseModel):
    content: str = Field(max_length=MAX_CONTENT_LENGTH)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        try:
            validate(value)  # {{name}} is the only placeholder; anything else is a typo
        except UnknownPlaceholders as exc:
            raise ValueError(str(exc)) from None
        return value


class SendRequest(ContentRequest):
    contact_id: int
    phone: str | None = None  # one of the contact's numbers; default: primary, else first

    @field_validator("phone")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        return None if value is None else normalize_e164(value)


class BulkSendRequest(ContentRequest):
    contact_ids: list[int] = Field(min_length=1, max_length=MAX_BULK_RECIPIENTS)


class Skipped(BaseModel):
    contact_id: int
    reason: str


class BulkSendResult(BaseModel):
    queued: list[MessageOut]
    skipped: list[Skipped]


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


def personalize(template: str, name: str) -> str | None:
    """The text for one recipient, or None if their name makes it longer than a message may be."""
    text = render(template, {"name": name})
    return text if len(text) <= MAX_CONTENT_LENGTH else None


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
    text = personalize(body.content, contact.name)
    if text is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, TOO_LONG_WITH_NAME)
    message = Message(
        channel="gsm", contact_id=contact.id, phone_number=chosen.phone_e164,
        content=text, status="queued", owner_id=caller.id,
    )  # fmt: skip
    db.add(message)
    db.commit()
    return to_out(db, [message])[0]


@router.post("/send-bulk", response_model=BulkSendResult, status_code=status.HTTP_201_CREATED)
def send_bulk(
    body: BulkSendRequest,
    caller: AuthUser = Depends(require("messages", "create")),
    db: Session = Depends(get_db),
) -> BulkSendResult:
    """Queue the same text for many contacts: one message each, to the contact's primary number
    (else its first). Contacts that cannot be messaged are skipped and reported, the rest are
    queued together in one transaction, in the order given."""
    ids = list(dict.fromkeys(body.contact_ids))  # each contact once, order kept
    contacts = {
        c.id: c.name
        for c in db.scalars(scope(select(Contact).where(Contact.id.in_(ids)), caller, "contacts"))
    }
    phones: dict[int, list[ContactPhone]] = {}
    for phone in db.scalars(
        select(ContactPhone).where(ContactPhone.contact_id.in_(contacts)).order_by(ContactPhone.id)
    ):
        phones.setdefault(phone.contact_id, []).append(phone)

    messages: list[Message] = []
    skipped: list[Skipped] = []
    for contact_id in ids:
        if contact_id not in contacts:  # also what an unreadable contact looks like
            skipped.append(Skipped(contact_id=contact_id, reason="contact not found"))
            continue
        numbers = phones.get(contact_id)
        if not numbers:
            skipped.append(Skipped(contact_id=contact_id, reason="no phone number"))
            continue
        text = personalize(body.content, contacts[contact_id])
        if text is None:
            skipped.append(Skipped(contact_id=contact_id, reason=TOO_LONG_WITH_NAME))
            continue
        chosen = next((p for p in numbers if p.is_primary), numbers[0])
        messages.append(
            Message(
                channel="gsm", contact_id=contact_id, phone_number=chosen.phone_e164,
                content=text, status="queued", owner_id=caller.id,
            )
        )  # fmt: skip
    db.add_all(messages)
    db.commit()
    return BulkSendResult(queued=to_out(db, messages), skipped=skipped)


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
