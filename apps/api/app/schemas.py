from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.phones import normalize_e164


class PhoneIn(BaseModel):
    phone: str
    label: str | None = Field(default=None, max_length=32)
    is_primary: bool = False

    @field_validator("phone")
    @classmethod
    def _normalize(cls, value: str) -> str:
        try:
            return normalize_e164(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from None


class PhoneOut(BaseModel):
    phone: str
    label: str | None
    is_primary: bool


class ContactFields(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    notes: str | None = None
    phones: list[PhoneIn] = []


class ContactIn(ContactFields):
    type: Literal["person", "entity"] = "person"


SortOrder = Literal["asc", "desc"]
