import phonenumbers

from app.config import settings


def normalize_e164(raw: str, region: str | None = None) -> str:
    """Return ``raw`` as an E.164 number, or raise ``ValueError`` if it is not a valid number."""
    try:
        parsed = phonenumbers.parse(raw, region or settings.default_phone_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"invalid phone number: {raw!r}") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError(f"invalid phone number: {raw!r}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
