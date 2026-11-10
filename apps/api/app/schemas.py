from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

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


class PartialNameParts(BaseModel):
    """Name parts as an update sends them: omitted stays as it is, ``null`` clears middle/last."""

    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)

    @field_validator("first_name", "middle_name", "last_name", mode="before")
    @classmethod
    def _tidy(cls, value: object) -> object:
        """Trim and collapse spaces; a blank middle or last name means "none"."""
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @field_validator("middle_name", "last_name")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None

    def apply_name(self, contact) -> None:
        """Write the parts the request carried onto ``contact``."""
        for part in ("first_name", "middle_name", "last_name"):
            if part in self.model_fields_set and not (part == "first_name" and self.first_name is None):
                setattr(contact, part, getattr(self, part))


class NameParts(PartialNameParts):
    """A person's name. An entity (type ``entity``) uses ``first_name`` for its whole name."""

    first_name: str = Field(min_length=1, max_length=255)


def check_entity_name(type_: str, middle_name: str | None, last_name: str | None) -> None:
    """An entity's whole name is its first name."""
    if type_ == "entity" and (middle_name or last_name):
        raise ValueError("an entity has only a first_name (its whole name)")


class ContactFields(NameParts):
    email: EmailStr | None = None
    notes: str | None = None
    phones: list[PhoneIn] = []


class ContactIn(ContactFields):
    type: Literal["person", "entity"] = "person"

    @model_validator(mode="after")
    def _entity_name(self):
        check_entity_name(self.type, self.middle_name, self.last_name)
        return self


SortOrder = Literal["asc", "desc"]
