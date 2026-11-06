"""Fantasy team totals for many teams at once (contests, challenges, leaderboards).

Late joiners only earn points recorded after they joined: their total is the team's points now
minus its points at the join watermark (see matches.late_window).
"""
from collections import defaultdict

from app.engines.scoring import LineupEntry, MatchContext, Pick, score_match, team_points
from app.engines.scoring.engine import effective_events
from app.live import lineup_entries, stream_events


def team_totals(conn, scores: dict, team_ids) -> dict:
    """{fantasy_team_id: total points} using the given athlete scores."""
    team_ids = list(team_ids)
    if not team_ids:
        return {}
    picks = defaultdict(list)
    for r in conn.execute("select fantasy_team_id, athlete_id, role from fantasy_team_picks "
                          "where fantasy_team_id = any(%s)", (team_ids,)).fetchall():
        picks[r["fantasy_team_id"]].append(Pick(str(r["athlete_id"]), r["role"]))
    return {tid: team_points(picks[tid], scores)[0] for tid in team_ids}


def snapshot_scores(conn, match: dict, scorer_id, after_event_id: int, elapsed_minutes: int) -> dict:
    """Athlete scores as they stood at a join watermark.

    Corrections are applied first, so undoing a pre-join event after someone joined neither
    costs nor gives them points.
    """
    lineup = [LineupEntry(str(r["athlete_id"]), str(r["team_id"]), r["position"], r["started"])
              for r in lineup_entries(conn, match)]
    events = stream_events(conn, match["id"], scorer_id) if scorer_id else []
    before = [e for e in effective_events(events) if e.id <= after_event_id]
    ctx = MatchContext(match["sport"], str(match["home_team_id"]), str(match["away_team_id"]),
                       match["scheduled_minutes"], match["rules_version"], elapsed_minutes)
    return score_match(ctx, lineup, before)


def late_watermark(*pairs):
    """Combine (after_event_id, elapsed) pairs from a late team and a late entry: the later wins."""
    present = [p for p in pairs if p[0] is not None]
    return max(present, key=lambda p: p[0]) if present else (None, None)


def totals_since(conn, match: dict, scorer_id, scores_now: dict, rows) -> dict:
    """rows: [(key, fantasy_team_id, after_event_id | None, elapsed | None)] -> {key: points}."""
    rows = list(rows)
    base = team_totals(conn, scores_now, {r[1] for r in rows})
    snapshots, out = {}, {}
    for key, team_id, after, elapsed in rows:
        if after is None:
            out[key] = base[team_id]
            continue
        if (after, elapsed) not in snapshots:
            snapshots[(after, elapsed)] = snapshot_scores(conn, match, scorer_id, after, elapsed or 0)
        out[key] = base[team_id] - team_totals(conn, snapshots[(after, elapsed)], [team_id])[team_id]
    return out
