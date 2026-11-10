"""Person names: one text in, ``(first, middle, last)`` out.

Contacts store the three parts; ``contacts.name`` is generated from them. The split here is only
for input that arrives as a single text (the import script, ``create-admin --name``); the last word
is the last name and anything between the first and last words is the middle name. Migration 0013
does the same split in SQL for existing rows.
"""


def split_name(full: str) -> tuple[str, str | None, str | None]:
    words = full.split()
    if not words:
        raise ValueError("name is empty")
    if len(words) == 1:
        return words[0], None, None
    return words[0], " ".join(words[1:-1]) or None, words[-1]
