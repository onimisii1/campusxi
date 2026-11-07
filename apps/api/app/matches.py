"""Shared match lookups, the lock rule, and the late-join window.

Teams, contests and challenges lock at scheduled start. After that, contests (and new teams)
stay joinable until LATE_JOIN_SHARE of the match; points recorded before joining don't count.

The match clock runs from the actual kick-off (`kicked_off_at`, set by "Kick off now" from the
admin screen or the scorer app), because campus matches rarely start on the dot. Until then the
clock stands still, for up to KICKOFF_GRACE after the scheduled time; without a kick-off tap it
runs from the scheduled start.
"""
import math
from datetime import timedelta

from app.errors import ApiError

OPEN_STATUSES = ("scheduled", "lineup_out")
IN_PLAY_STATUSES = ("scheduled", "lineup_out", "live")
LATE_JOIN_SHARE = 0.67        # agreed 6 Nov 2026: join until 67% of the match
LATE_FEE_BPS = 15000          # late entries pay 150% of the entry fee; the extra grows the pool
KICKOFF_GRACE = timedelta(minutes=30)

MATCH_SQL = """
    select m.*, t.sport, t.school_id, t.status as tournament_status, t.name as tournament,
           h.name as home_team, a.name as away_team, h.colour as home_colour, a.colour as away_colour,
           h.logo_url as home_logo, a.logo_url as away_logo
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


def clock_start(match: dict, now):
    """When the match clock started, or None if the match hasn't kicked off yet."""
    if match.get("kicked_off_at"):
        return match["kicked_off_at"]
    if match["status"] in OPEN_STATUSES and now < match["scheduled_start"] + KICKOFF_GRACE:
        return None
    return match["scheduled_start"]


def match_minute(conn, match: dict, now) -> int:
    """How far the match has got: the later of the clock since kick-off and the latest recorded
    event minute."""
    start = clock_start(match, now)
    wall = 0 if start is None else max(0, int((now - start).total_seconds() // 60))
    latest = conn.execute("select max(minute) as m from stat_events where match_id = %s",
                          (match["id"],)).fetchone()["m"]
    return max(wall, latest or 0)


def late_window(conn, match: dict, now) -> dict | None:
    """{'minute', 'until_minute'} while late joining is open, otherwise None."""
    if not is_locked(match, now) or match["status"] not in IN_PLAY_STATUSES or match["scheduled_minutes"] <= 0:
        return None
    until = math.floor(match["scheduled_minutes"] * LATE_JOIN_SHARE)
    minute = match_minute(conn, match, now)
    return {"minute": minute, "until_minute": until} if minute < until else None


def event_watermark(conn, match_id) -> int:
    """The highest stat event recorded for the match so far; later events count for late joiners."""
    return conn.execute("select coalesce(max(id), 0) as w from stat_events where match_id = %s",
                        (match_id,)).fetchone()["w"]


def assert_open_or_late(conn, match: dict, now) -> dict | None:
    """None when the match is still open; the late-join info when joining late; else 409."""
    if not is_locked(match, now):
        return None
    window = late_window(conn, match, now)
    if window is None:
        raise ApiError(409, "match_locked", "this match has locked and late joining has closed")
    return {**window, "after_event_id": event_watermark(conn, match["id"])}


KICKOFF_EARLIEST = timedelta(minutes=30)   # same window in which scorers may start recording


def kick_off(conn, match: dict, now) -> dict:
    """Start the match clock now. Locks teams if the scheduled start hasn't come yet (status live)."""
    if match.get("kicked_off_at"):
        raise ApiError(409, "already_kicked_off", "this match has already kicked off")
    if match["status"] not in IN_PLAY_STATUSES:
        raise ApiError(409, "cannot_kick_off", f"this match is {match['status']}")
    if now < match["scheduled_start"] - KICKOFF_EARLIEST:
        raise ApiError(409, "too_early", "a match can kick off at most 30 minutes before its scheduled time; "
                                         "move the time first")
    conn.execute("update matches set kicked_off_at = %s, status = 'live' where id = %s", (now, match["id"]))
    return {"match_id": match["id"], "status": "live", "kicked_off_at": now}


def late_fee(entry_fee_kobo: int) -> int:
    return entry_fee_kobo * LATE_FEE_BPS // 10000


def squad(conn, match: dict) -> list:
    return conn.execute(
        """select a.id, a.team_id, a.display_name, a.position from athletes a
           where a.team_id in (%s, %s) and a.active order by a.team_id, a.position, a.display_name""",
        (match["home_team_id"], match["away_team_id"]),
    ).fetchall()
