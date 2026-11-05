"""Points from a scorer's event stream, via the pure scoring engine.

Live points follow the primary scorer's stream; once the admin confirms the result,
the stream they named as official is the one that counts.
"""
from collections import Counter

from app.engines.scoring import LineupEntry, MatchContext, StatEvent, score_match
from app.engines.scoring.engine import effective_events


def official_or_primary_scorer(conn, match: dict):
    if match["status"] == "confirmed":
        row = conn.execute("select official_scorer_id as id from match_results where match_id = %s",
                           (match["id"],)).fetchone()
    else:
        row = conn.execute("select user_id as id from match_scorers where match_id = %s and role = 'primary'",
                           (match["id"],)).fetchone()
    return row["id"] if row else None


def lineup_entries(conn, match: dict) -> list:
    rows = conn.execute(
        """select l.athlete_id, l.started, a.team_id, a.position, a.display_name
           from match_lineups l join athletes a on a.id = l.athlete_id where l.match_id = %s""",
        (match["id"],),
    ).fetchall()
    return rows


def stream_events(conn, match_id, scorer_id) -> list:
    rows = conn.execute(
        """select id, athlete_id, event_type, minute, amount, reverses_event_id from stat_events
           where match_id = %s and scorer_id = %s order by client_seq""",
        (match_id, scorer_id),
    ).fetchall()
    return [StatEvent(r["id"], str(r["athlete_id"]), r["event_type"], r["minute"], r["amount"],
                      r["reverses_event_id"]) for r in rows]


IN_PLAY = ("scheduled", "lineup_out", "live")


def elapsed_minutes(match: dict, now) -> int | None:
    """Minutes played so far while in play (from scheduled kick-off); None once finished."""
    if match["status"] not in IN_PLAY or now is None:
        return None
    played = int((now - match["scheduled_start"]).total_seconds() // 60)
    return max(0, min(played, match["scheduled_minutes"]))


def context(match: dict, now=None) -> MatchContext:
    return MatchContext(match["sport"], str(match["home_team_id"]), str(match["away_team_id"]),
                        match["scheduled_minutes"], match["rules_version"], elapsed_minutes(match, now))


def stream_scores(conn, match: dict, scorer_id, now=None) -> dict:
    """{athlete_id: AthleteScore} for every athlete in the published line-up.

    Pass `now` for live views so time-based awards only count minutes played so far.
    """
    lineup = [LineupEntry(str(r["athlete_id"]), str(r["team_id"]), r["position"], r["started"])
              for r in lineup_entries(conn, match)]
    events = stream_events(conn, match["id"], scorer_id) if scorer_id else []
    return score_match(context(match, now), lineup, events)


def tallies(conn, match_id, scorer_id) -> Counter:
    """(athlete_id, event_type) -> total amount, after corrections."""
    out = Counter()
    for e in effective_events(stream_events(conn, match_id, scorer_id)):
        out[(e.athlete_id, e.type)] += e.amount
    return out
