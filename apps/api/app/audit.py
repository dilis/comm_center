"""Writing the activity log and the login log.

Both helpers only add a row to the caller's session: the row commits (or rolls back) together with
the change it describes, so the log never claims something that did not happen.
"""

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import ActivityLog, LoginLog


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def record_activity(
    db: Session,
    request: Request,
    user_id: int,
    action: str,
    resource: str,
    resource_id: int | None,
    summary: str,
) -> None:
    db.add(
        ActivityLog(
            user_id=user_id, action=action, resource=resource, resource_id=resource_id,
            summary=summary[:500], ip=client_ip(request),
        )
    )  # fmt: skip


def record_login(
    db: Session, request: Request, event: str, username: str, user_id: int | None = None
) -> None:
    db.add(LoginLog(event=event, username=username[:255], user_id=user_id, ip=client_ip(request)))
