"""The shared list envelope: ``items``, ``total``, ``page`` and ``page_size``."""

from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 100


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass
class PageParams:
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE)


def paginate(db: Session, stmt: Select, params: PageParams, *order_by) -> tuple[list, int]:
    """Rows of one page plus the total, both computed from the same (already scoped) ``stmt``."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(
        stmt.order_by(*order_by)
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
    ).all()
    return list(rows), total
