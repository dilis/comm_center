import phonenumbers

from app.config import settings


def normalize_e164(raw: str, region: str | None = None, *, strict: bool = True) -> str:
    """Return ``raw`` as an E.164 number, or raise ``ValueError`` if it is not a valid number.

    With ``strict=False`` a number that is merely possible (right length for its country) is
    accepted too, for numbers that are only shown, such as a device's own SIM: numbering plans lag
    behind carriers, so a new range can be real before the library knows it."""
    try:
        parsed = phonenumbers.parse(raw, region or settings.default_phone_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"invalid phone number: {raw!r}") from exc
    ok = phonenumbers.is_valid_number(parsed) or (
        not strict and phonenumbers.is_possible_number(parsed)
    )
    if not ok:
        raise ValueError(f"invalid phone number: {raw!r}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
