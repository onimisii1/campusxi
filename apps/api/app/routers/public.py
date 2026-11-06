"""Lobby reads (PRD 8.2): sports, schools, published tournaments and matches."""
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import optional_user
from app.clock import utcnow
from app.competition import bracket, player_stats, scoreline, standings
from app.db import get_conn
from app.engines.payouts import final_ranks
from app.errors import ApiError
from app.fantasy import totals_since
from app.live import lineup_entries, official_or_primary_scorer, stream_scores
from app.engines.scoring.rules import (
    CURRENT_VERSION, MAX_TEAMS_PER_MATCH, MULTIPLIERS, SCORING_RULES, TEAM_RULES,
)
from app.matches import LATE_FEE_BPS, LATE_JOIN_SHARE, MATCH_SQL, is_locked, late_window, load_match, squad

router = APIRouter(tags=["lobby"])


@router.get("/sports")
def list_sports(conn=Depends(get_conn)):
    return conn.execute("select code, name, live from sports order by sort_order").fetchall()


@router.get("/sports/{code}/rules")
def sport_rules(code: str):
    """Rules tab: team rules and the full points table, straight from the scoring engine."""
    if code not in CURRENT_VERSION:
        raise ApiError(404, "sport_not_found", "no rules for that sport yet")
    rules, team = SCORING_RULES[CURRENT_VERSION[code]], TEAM_RULES[code]
    labels = {"point": "Each point scored", "sub_on": "Comes on as a substitute"}
    scoring = [{"event": "In the starting line-up", "points": rules.appearance["start"]},
               {"event": "Comes on as a substitute", "points": rules.appearance["sub_on"]}]
    for event, by_pos in rules.position_events.items():
        for pos, pts in by_pos.items():
            scoring.append({"event": f"{event.replace('_', ' ').capitalize()} ({pos})", "points": pts})
    scoring += [{"event": labels.get(e, e.replace("_", " ").capitalize()), "points": p} for e, p in rules.events.items()]
    if rules.clean_sheet:
        scoring.append({"event": f"Clean sheet ({'/'.join(sorted(rules.clean_sheet_positions))}, "
                                 f"{int(rules.clean_sheet_min_share * 100)}% of the match on the pitch)",
                        "points": rules.clean_sheet})
    if rules.goal_conceded:
        scoring.append({"event": f"Goal conceded while on the pitch ({'/'.join(sorted(rules.goal_conceded_positions))})",
                        "points": rules.goal_conceded})
    return {
        "sport": code, "version": rules.version, "team_size": team.size, "max_per_side": team.max_per_side,
        "positions": [{"name": g.name, "positions": sorted(g.positions), "min": g.min, "max": g.max} for g in team.groups],
        "multipliers": {"captain": MULTIPLIERS["captain"], "vice_captain": MULTIPLIERS["vice_captain"],
                        "key": MULTIPLIERS["key"]},
        "max_teams_per_match": MAX_TEAMS_PER_MATCH,
        "late_join": {"until_share": LATE_JOIN_SHARE, "fee_multiplier": LATE_FEE_BPS / 10000},
        "scoring": scoring,
    }


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
    t["teams"] = conn.execute("select id, name, colour from teams where tournament_id = %s order by name",
                              (tournament_id,)).fetchall()
    return t


def _published(conn, tournament_id) -> dict:
    t = conn.execute("select * from tournaments where id = %s and status = 'published'", (tournament_id,)).fetchone()
    if t is None:
        raise ApiError(404, "tournament_not_found", "tournament not found")
    return t


@router.get("/tournaments/{tournament_id}/standings")
def tournament_standings(tournament_id: UUID, conn=Depends(get_conn)):
    """League table from confirmed results (walkovers included)."""
    t = _published(conn, tournament_id)
    return {"tournament_id": t["id"], "sport": t["sport"], "rows": standings(conn, t)}


@router.get("/tournaments/{tournament_id}/stats")
def tournament_stats(tournament_id: UUID, conn=Depends(get_conn)):
    """Golden boot (football) or MVP table (basketball) from official stats."""
    t = _published(conn, tournament_id)
    return {"tournament_id": t["id"], "sport": t["sport"], **player_stats(conn, t)}


@router.get("/tournaments/{tournament_id}/bracket")
def tournament_bracket(tournament_id: UUID, conn=Depends(get_conn)):
    t = _published(conn, tournament_id)
    return {"tournament_id": t["id"], **bracket(conn, t)}


@router.get("/tournaments/{tournament_id}/leaderboard")
def season_leaderboard(tournament_id: UUID, user=Depends(optional_user), conn=Depends(get_conn)):
    """Free season-long leaderboard (PRD F3): each player's best team score per confirmed match, summed."""
    t = conn.execute("select id, name, sport from tournaments where id = %s and status = 'published'",
                     (tournament_id,)).fetchone()
    if t is None:
        raise ApiError(404, "tournament_not_found", "tournament not found")
    totals, matches_played = defaultdict(Decimal), defaultdict(int)
    # Walkovers and imported results had no fantasy play.
    confirmed = conn.execute(
        """select m.id from matches m join match_results r on r.match_id = m.id
           where m.tournament_id = %s and m.status = 'confirmed' and not r.walkover and not r.imported""",
        (tournament_id,)).fetchall()
    for row in confirmed:
        m = load_match(conn, row["id"])
        scorer = official_or_primary_scorer(conn, m)
        scores = stream_scores(conn, m, scorer)
        teams = conn.execute(TEAMS_SQL, (m["id"],)).fetchall()
        team_pts = _team_points(conn, m, scorer, scores, teams)
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


TEAMS_SQL = "select id, user_id, late_after_event_id, late_elapsed_minutes from fantasy_teams where match_id = %s"


def _team_points(conn, m, scorer, scores, teams) -> dict:
    """{team_id: points}; a team built late only counts points recorded after it was built."""
    return totals_since(conn, m, scorer, scores,
                        [(t["id"], t["id"], t["late_after_event_id"], t["late_elapsed_minutes"]) for t in teams])


def _card(m, now, conn):
    seconds = int((m["scheduled_start"] - now).total_seconds())
    late = late_window(conn, m, now)
    return {
        "id": m["id"], "tournament_id": m["tournament_id"], "tournament": m["tournament"], "sport": m["sport"],
        "home_team": {"id": m["home_team_id"], "name": m["home_team"], "colour": m["home_colour"]},
        "away_team": {"id": m["away_team_id"], "name": m["away_team"], "colour": m["away_colour"]},
        "venue": m["venue"], "scheduled_start": m["scheduled_start"], "status": m["status"],
        "lineup_out": m["status"] == "lineup_out", "locked": is_locked(m, now),
        "seconds_to_lock": max(0, seconds),
        "late_join_until": late["until_minute"] if late else None,
        "code": m["code"], "stage": m["stage"], "kicked_off_at": m["kicked_off_at"],
        "score": scoreline(conn, m),
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
    return [_card(m, now, conn) for m in rows]


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


@router.get("/matches/{match_id}/summary")
def match_summary(match_id: UUID, user=Depends(optional_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """Home-card numbers: your best team's points, the average and the highest (best team per player)."""
    m = load_match(conn, match_id)
    teams = conn.execute(TEAMS_SQL, (match_id,)).fetchall()
    me = user["id"] if user else None
    out = {"match_id": match_id, "status": m["status"], "players": len({t["user_id"] for t in teams}),
           "teams": len(teams), "my_teams": sum(1 for t in teams if t["user_id"] == me),
           "my_points": None, "average": None, "highest": None}
    if m["status"] not in ("live", "final_pending", "confirmed") or not teams:
        return out
    scorer = official_or_primary_scorer(conn, m)
    scores = stream_scores(conn, m, scorer, now)
    totals = _team_points(conn, m, scorer, scores, teams)
    best = {}
    for t in teams:
        best[t["user_id"]] = max(best.get(t["user_id"], totals[t["id"]]), totals[t["id"]])
    out["average"] = (sum(best.values()) / len(best)).quantize(Decimal("0.1"))
    out["highest"] = max(best.values())
    out["my_points"] = best.get(me)
    return out


@router.get("/matches/{match_id}")
def get_match(match_id: UUID, conn=Depends(get_conn), now=Depends(utcnow)):
    m = load_match(conn, match_id)
    lineup = {r["athlete_id"]: r["started"] for r in conn.execute(
        "select athlete_id, started from match_lineups where match_id = %s", (match_id,)).fetchall()}
    out = _card(m, now, conn)
    out["scheduled_minutes"] = m["scheduled_minutes"]
    out["squads"] = {"home": [], "away": []}
    for a in squad(conn, m):
        side = "home" if a["team_id"] == m["home_team_id"] else "away"
        status = None if a["id"] not in lineup else ("starting" if lineup[a["id"]] else "bench")
        out["squads"][side].append({"id": a["id"], "name": a["display_name"], "position": a["position"],
                                    "lineup": status})
    return out
