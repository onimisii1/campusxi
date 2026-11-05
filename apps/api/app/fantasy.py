"""Fantasy team totals for many teams at once (contests, challenges, leaderboards)."""
from collections import defaultdict

from app.engines.scoring import Pick, team_points


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
