"""Lobby reads (PRD 8.2): sports, schools, published tournaments and matches."""
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import optional_user
from app.clock import utcnow
from app.db import get_conn
from app.engines.payouts import final_ranks
from app.errors import ApiError
from app.fantasy import team_totals
from app.live import lineup_entries, official_or_primary_scorer, stream_scores
from app.matches import MATCH_SQL, is_locked, load_match, squad

router = APIRouter(tags=["lobby"])


@router.get("/sports")
def list_sports(conn=Depends(get_conn)):
    return conn.execute("select code, name, live from sports order by sort_order").fetchall()


@router.get("/schools")
def list_schools(conn=Depends(get_conn)):
    return conn.execute("select id, name from schools order by name").fetchall()


@router.get("/tournaments")
def list_tournaments(school_id: UUID | None = None, sport: str | None = None, conn=Depends(get_conn)):
    return conn.execute(
        """select id, school_id, sport, name, match_minutes, starts_on, ends_on from tournaments
           where status = 'published'
             and (%(school)s::uuid is null or school_id = %(school)s)
             and (%(sport)s::text is null or sport = %(sport)s)
           order by starts_on nulls last, name""",
        {"school": school_id, "sport": sport},
    ).fetchall()


@router.get("/tournaments/{tournament_id}")
def get_tournament(tournament_id: UUID, conn=Depends(get_conn)):
    t = conn.execute("select * from tournaments where id = %s and status = 'published'",
                     (tournament_id,)).fetchone()
    if t is None:
        raise ApiError(404, "tournament_not_found", "tournament not found")
    t["teams"] = conn.execute("select id, name from teams where tournament_id = %s order by name",
                              (tournament_id,)).fetchall()
    return t


@router.get("/tournaments/{tournament_id}/leaderboard")
def season_leaderboard(tournament_id: UUID, user=Depends(optional_user), conn=Depends(get_conn)):
    """Free season-long leaderboard (PRD F3): each player's best team score per confirmed match, summed."""
    t = conn.execute("select id, name, sport from tournaments where id = %s and status = 'published'",
                     (tournament_id,)).fetchone()
    if t is None:
        raise ApiError(404, "tournament_not_found", "tournament not found")
    totals, matches_played = defaultdict(Decimal), defaultdict(int)
    confirmed = conn.execute("select id from matches where tournament_id = %s and status = 'confirmed'",
                             (tournament_id,)).fetchall()
    for row in confirmed:
        m = load_match(conn, row["id"])
        scores = stream_scores(conn, m, official_or_primary_scorer(conn, m))
        teams = conn.execute("select id, user_id from fantasy_teams where match_id = %s", (m["id"],)).fetchall()
        team_pts = team_totals(conn, scores, [r["id"] for r in teams])
        best = {}
        for r in teams:
            best[r["user_id"]] = max(best.get(r["user_id"], team_pts[r["id"]]), team_pts[r["id"]])
        for uid, pts in best.items():
            totals[uid] += pts
            matches_played[uid] += 1
    names = {r["id"]: r["team_name"] for r in conn.execute(
        "select id, team_name from users where id = any(%s)", (list(totals),)).fetchall()}
    ranks = final_ranks(list(totals.items()))
    rows = [{"rank": ranks[uid], "team_name": names[uid], "points": pts, "matches": matches_played[uid],
             "is_me": bool(user and uid == user["id"])} for uid, pts in totals.items()]
    rows.sort(key=lambda r: (r["rank"], r["team_name"].lower()))
    return {"tournament_id": tournament_id, "name": t["name"], "sport": t["sport"],
            "matches_confirmed": len(confirmed), "entries": rows}


def _card(m, now):
    seconds = int((m["scheduled_start"] - now).total_seconds())
    return {
        "id": m["id"], "tournament_id": m["tournament_id"], "tournament": m["tournament"], "sport": m["sport"],
        "home_team": {"id": m["home_team_id"], "name": m["home_team"]},
        "away_team": {"id": m["away_team_id"], "name": m["away_team"]},
        "venue": m["venue"], "scheduled_start": m["scheduled_start"], "status": m["status"],
        "lineup_out": m["status"] == "lineup_out", "locked": is_locked(m, now),
        "seconds_to_lock": max(0, seconds),
    }


@router.get("/matches")
def list_matches(sport: str | None = None, status: str | None = None, tournament_id: UUID | None = None,
                 conn=Depends(get_conn), now=Depends(utcnow)):
    rows = conn.execute(
        MATCH_SQL + """ where t.status = 'published'
             and (%(sport)s::text is null or t.sport = %(sport)s)
             and (%(status)s::text is null or m.status = %(status)s)
             and (%(tid)s::uuid is null or m.tournament_id = %(tid)s)
           order by m.scheduled_start""",
        {"sport": sport, "status": status, "tid": tournament_id},
    ).fetchall()
    return [_card(m, now) for m in rows]


@router.get("/matches/{match_id}/live")
def live_points(match_id: UUID, conn=Depends(get_conn), now=Depends(utcnow)):
    """Athlete points with explanations (PRD F1, F2): primary stream while live, official once confirmed."""
    m = load_match(conn, match_id)
    scorer = official_or_primary_scorer(conn, m)
    scores = stream_scores(conn, m, scorer, now)
    side = {m["home_team_id"]: "home", m["away_team_id"]: "away"}
    athletes = [{
        "id": r["athlete_id"], "name": r["display_name"], "position": r["position"], "side": side[r["team_id"]],
        "points": scores[str(r["athlete_id"])].points,
        "breakdown": [{"label": label, "points": pts} for label, pts in scores[str(r["athlete_id"])].breakdown],
    } for r in lineup_entries(conn, m)]
    athletes.sort(key=lambda a: (-a["points"], a["name"]))
    result = conn.execute("select home_score, away_score, winner, shootout_winner from match_results "
                          "where match_id = %s", (match_id,)).fetchone()
    return {"match_id": match_id, "status": m["status"],
            "source": "official" if m["status"] == "confirmed" else ("primary_scorer" if scorer else None),
            "result": result, "athletes": athletes}


@router.get("/matches/{match_id}")
def get_match(match_id: UUID, conn=Depends(get_conn), now=Depends(utcnow)):
    m = load_match(conn, match_id)
    lineup = {r["athlete_id"]: r["started"] for r in conn.execute(
        "select athlete_id, started from match_lineups where match_id = %s", (match_id,)).fetchall()}
    out = _card(m, now)
    out["scheduled_minutes"] = m["scheduled_minutes"]
    out["squads"] = {"home": [], "away": []}
    for a in squad(conn, m):
        side = "home" if a["team_id"] == m["home_team_id"] else "away"
        status = None if a["id"] not in lineup else ("starting" if lineup[a["id"]] else "bench")
        out["squads"][side].append({"id": a["id"], "name": a["display_name"], "position": a["position"],
                                    "lineup": status})
    return out
