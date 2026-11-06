"""Shared match lookups and the lock rule (teams, contests and bets lock at scheduled start)."""
from app.errors import ApiError

OPEN_STATUSES = ("scheduled", "lineup_out")

MATCH_SQL = """
    select m.*, t.sport, t.school_id, t.status as tournament_status, t.name as tournament,
           h.name as home_team, a.name as away_team, h.colour as home_colour, a.colour as away_colour
    from matches m
    join tournaments t on t.id = m.tournament_id
    join teams h on h.id = m.home_team_id
    join teams a on a.id = m.away_team_id
"""


def load_match(conn, match_id, published_only: bool = True) -> dict:
    match = conn.execute(MATCH_SQL + " where m.id = %s", (match_id,)).fetchone()
    if match is None or (published_only and match["tournament_status"] != "published"):
        raise ApiError(404, "match_not_found", "match not found")
    return match


def is_locked(match: dict, now) -> bool:
    return match["status"] not in OPEN_STATUSES or now >= match["scheduled_start"]


def assert_open(match: dict, now):
    if is_locked(match, now):
        raise ApiError(409, "match_locked", "this match has locked; teams can no longer change")


def squad(conn, match: dict) -> list:
    return conn.execute(
        """select a.id, a.team_id, a.display_name, a.position from athletes a
           where a.team_id in (%s, %s) and a.active order by a.team_id, a.position, a.display_name""",
        (match["home_team_id"], match["away_team_id"]),
    ).fetchall()
