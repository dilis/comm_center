"""Create the first administrator. No default credential ships in a migration."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.models import AccessGroup, Contact, User, UserGroup
from app.names import split_name

SYSTEM_USER_ID = 1


class BootstrapError(Exception):
    pass


def create_admin(db: Session, username: str, password: str, name: str) -> User:
    """Create a human user in the ``admin`` group. Refuses to run once a human user exists."""
    if len(password) < security.MIN_PASSWORD_LENGTH:
        raise BootstrapError(f"password must be at least {security.MIN_PASSWORD_LENGTH} characters")
    if db.scalars(select(User.id).where(User.is_system.is_(False)).limit(1)).first():
        raise BootstrapError("a user already exists; create further users through the API")
    admin_group = db.scalars(select(AccessGroup).where(AccessGroup.name == "admin")).one_or_none()
    if admin_group is None:
        raise BootstrapError("the 'admin' group is missing; run the database migrations first")

    first, middle, last = split_name(name)
    contact = Contact(
        first_name=first, middle_name=middle, last_name=last, type="person", owner_id=SYSTEM_USER_ID
    )
    db.add(contact)
    db.flush()
    user = User(
        contact_id=contact.id,
        username=username,
        password_hash=security.hash_password(password),
        owner_id=SYSTEM_USER_ID,
    )
    db.add(user)
    db.flush()
    db.add(UserGroup(user_id=user.id, group_id=admin_group.id))
    db.commit()
    return user
