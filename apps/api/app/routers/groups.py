from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz import AuthUser, group_permissions, require
from app.db import get_db
from app.models import AccessGroup
from app.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/groups", tags=["groups"])


class GroupOut(BaseModel):
    id: int
    name: str
    is_system: bool
    permissions: list[str]  # effective ("resource:action"): own plus all descendants'


@router.get("", response_model=Page[GroupOut])
def list_groups(
    params: PageParams = Depends(),
    _: AuthUser = Depends(require("groups", "read_all")),
    db: Session = Depends(get_db),
) -> Page[GroupOut]:
    groups, total = paginate(db, select(AccessGroup), params, AccessGroup.name, AccessGroup.id)
    perms = group_permissions(db, [g.id for g in groups])
    items = [
        GroupOut(
            id=g.id,
            name=g.name,
            is_system=g.is_system,
            permissions=sorted(f"{r}:{a}" for r, a in perms.get(g.id, set())),
        )
        for g in groups
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)
