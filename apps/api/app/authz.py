"""Authorization: effective permissions, ``require``, read ``scope`` and the escalation check."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, aliased

from app.messaging import inbound_agent_ids
from app.models import (
    AccessGroup,
    Contact,
    GroupClosure,
    GroupPermission,
    Message,
    Permission,
    User,
    UserGroup,
)

PermissionPair = tuple[str, str]


@dataclass(frozen=True)
class AuthUser:
    """The authenticated caller with the permissions held at the time of this request."""

    id: int
    permissions: frozenset[PermissionPair]

    def can(self, resource: str, action: str) -> bool:
        return (resource, action) in self.permissions


def is_subset(wanted: Iterable[PermissionPair], held: Iterable[PermissionPair]) -> bool:
    """True if ``held`` covers every wanted permission.

    ``read_all`` covers the narrower reads (``read_own``, ``read_received``) of the same resource:
    without that, an admin (who holds ``messages:read_all`` only) could not hand out ``agent``.
    """
    held_set = set(held)
    covered = held_set | {
        (resource, narrower)
        for resource, action in held_set
        if action == "read_all"
        for narrower in ("read_own", "read_received")
    }
    return set(wanted) <= covered


def group_permissions(db: Session, group_ids_stmt) -> dict[int, set[PermissionPair]]:
    """Effective permissions per group (own plus all descendants) for the groups selected."""
    ancestor = aliased(AccessGroup)
    rows = db.execute(
        select(GroupClosure.ancestor_id, Permission.resource, Permission.action)
        .join(GroupPermission, GroupPermission.group_id == GroupClosure.descendant_id)
        .join(Permission, Permission.id == GroupPermission.permission_id)
        # AccessGroup and its alias both carry the soft-delete filter: a deleted group, or a
        # deleted descendant, contributes nothing.
        .join(AccessGroup, AccessGroup.id == GroupClosure.descendant_id)
        .join(ancestor, ancestor.id == GroupClosure.ancestor_id)
        .where(GroupClosure.ancestor_id.in_(group_ids_stmt))
    )
    result: dict[int, set[PermissionPair]] = {}
    for group_id, resource, action in rows:
        result.setdefault(group_id, set()).add((resource, action))
    return result


def effective_permissions(db: Session, user_id: int) -> frozenset[PermissionPair]:
    """Union over the user's groups; read from the database on every call (never cached)."""
    stmt = select(UserGroup.group_id).where(UserGroup.user_id == user_id)
    perms: set[PermissionPair] = set()
    for group_perms in group_permissions(db, stmt).values():
        perms |= group_perms
    return frozenset(perms)


def check_assignable_groups(db: Session, caller: AuthUser, group_ids: Iterable[int]) -> None:
    """Escalation rule: every group's effective permissions must be a subset of the caller's.

    Unknown or deleted groups are rejected with 422, groups beyond the caller's own with 403.
    """
    wanted = set(group_ids)
    if not wanted:
        return
    known = set(db.scalars(select(AccessGroup.id).where(AccessGroup.id.in_(wanted))))
    if known != wanted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown group")
    per_group = group_permissions(db, wanted)
    for group_id in wanted:
        if not is_subset(per_group.get(group_id, set()), caller.permissions):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "cannot assign a group with permissions you lack"
            )


def forbidden() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "permission denied")


def require(resource: str, action: str) -> Callable[..., AuthUser]:
    """Endpoint-level check: ``Depends(require("contacts", "create"))``."""
    from app.deps import get_current_user

    def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not user.can(resource, action):
            raise forbidden()
        return user

    return dependency


def scope(stmt: Select, user: AuthUser, resource: str) -> Select:
    """Restrict a select of ``resource`` rows to what ``user`` may read.

    ``update`` and ``delete`` reuse this scope. Raises 403 when the user has no read permission.
    Messages: ``read_all``, else (``read_own`` and owned by me) or (``read_received`` and owned
    by an inbound system agent). Everything else: ``read_all``, else ``read_own`` and owned by me.
    """
    if user.can(resource, "read_all"):
        return stmt
    if resource == "messages":
        clauses = []
        if user.can("messages", "read_own"):
            clauses.append(Message.owner_id == user.id)
        if user.can("messages", "read_received"):
            clauses.append(Message.owner_id.in_(inbound_agent_ids()))
        if not clauses:
            raise forbidden()
        return stmt.where(or_(*clauses))
    model = _OWNED_MODELS.get(resource)
    if model is not None and user.can(resource, "read_own"):
        return stmt.where(model.owner_id == user.id)
    raise forbidden()


_OWNED_MODELS = {"users": User, "contacts": Contact}
