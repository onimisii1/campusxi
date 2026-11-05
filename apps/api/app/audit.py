import json

from psycopg.types.json import Jsonb


def audit(conn, actor_id, action: str, target_type: str | None = None, target_id=None, **details):
    """Append an admin action to the append-only audit_log."""
    conn.execute(
        "insert into audit_log (actor_id, action, target_type, target_id, details) values (%s, %s, %s, %s, %s)",
        (actor_id, action, target_type, target_id, Jsonb(json.loads(json.dumps(details, default=str)))),
    )
