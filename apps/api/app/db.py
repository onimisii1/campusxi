"""One psycopg connection per request: committed on success, rolled back on any error."""
import psycopg
from psycopg.rows import dict_row

from app.config import settings


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or settings.database_url, row_factory=dict_row)


def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
