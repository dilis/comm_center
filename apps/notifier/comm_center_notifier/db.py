"""Opening a connection to the database from ``DATABASE_URL`` (``mysql+pymysql://user:pw@host:port/db``)."""

from collections.abc import Callable
from urllib.parse import unquote, urlparse

import pymysql
import pymysql.cursors

from comm_center_notifier.config import settings

Connect = Callable[[], pymysql.Connection]


def connect() -> pymysql.Connection:
    """A new connection with transactions (commit explicitly) and dictionary rows."""
    url = urlparse(settings.database_url)
    return pymysql.connect(
        host=url.hostname or "127.0.0.1",
        port=url.port or 3306,
        user=unquote(url.username or ""),
        password=unquote(url.password or ""),
        database=url.path.lstrip("/"),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
