"""One psycopg connection per request: committed on success, rolled back on any error."""
import psycopg
from psycopg.rows import dict_row

from app.config import settings


def connect(url: str | None = None) -> psycopg.Connection:
    # prepare_threshold=None: no server-side prepared statements, so the API works through Supabase's
    # Transaction pooler (port 6543, used on Vercel), where a statement prepared on one server
    # connection isn't there on the next. Harmless on direct and session connections.
    return psycopg.connect(url or settings.database_url, row_factory=dict_row, prepare_threshold=None)


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
