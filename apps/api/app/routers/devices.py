from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz import AuthUser, require
from app.db import get_db
from app.models import GsmDevice

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceOut(BaseModel):
    id: int
    name: str
    phone_number: str
    status: Literal["online", "offline", "error"]
    last_error: str | None  # latest modem problem; kept after recovery
    last_error_at: datetime | None


@router.get("", response_model=list[DeviceOut])
def list_devices(
    _: AuthUser = Depends(require("messages", "read_all")),
    db: Session = Depends(get_db),
) -> list[GsmDevice]:
    """Modem health for people who may read every message. Devices are registered from the
    command line, never through the API."""
    return list(db.scalars(select(GsmDevice).order_by(GsmDevice.name, GsmDevice.id)))
