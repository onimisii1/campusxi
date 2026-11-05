"""Fantasy team builder (PRD 5.3, 8.3): uniform pricing, up to 10 teams per match, edits until lock."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.clock import utcnow
from app.db import get_conn
from app.engines.scoring import (
    MAX_TEAMS_PER_MATCH, Pick, SquadAthlete, team_points, team_signature, validate_team,
)
from app.errors import ApiError
from app.live import official_or_primary_scorer, stream_scores
from app.matches import assert_open, load_match, squad
from app.schemas import TeamIn

router = APIRouter(tags=["teams"])


def _picks(body: TeamIn) -> list:
    return [Pick(str(p.athlete_id), p.role) for p in body.picks]


def _check_team(conn, match, picks):
    members = [SquadAthlete(str(a["id"]), str(a["team_id"]), a["position"]) for a in squad(conn, match)]
    errors = validate_team(match["sport"], picks, members)
    if errors:
        raise ApiError(422, "invalid_team", "this team breaks the team rules", errors)


def _check_duplicate(conn, user_id, match_id, picks, exclude_team_id=None):
    rows = conn.execute(
        """select ft.id, p.athlete_id, p.role from fantasy_teams ft
           join fantasy_team_picks p on p.fantasy_team_id = ft.id
           where ft.user_id = %s and ft.match_id = %s and ft.id is distinct from %s""",
        (user_id, match_id, exclude_team_id),
    ).fetchall()
    existing = {}
    for r in rows:
        existing.setdefault(r["id"], []).append(Pick(str(r["athlete_id"]), r["role"]))
    sig = team_signature(picks)
    if any(team_signature(p) == sig for p in existing.values()):
        raise ApiError(409, "duplicate_team", "you already have a team with exactly these picks")


def _write_picks(conn, team_id, picks):
    conn.execute("delete from fantasy_team_picks where fantasy_team_id = %s", (team_id,))
    with conn.cursor() as cur:
        cur.executemany("insert into fantasy_team_picks (fantasy_team_id, athlete_id, role) values (%s, %s, %s)",
                        [(team_id, p.athlete_id, p.role) for p in picks])


def _team_out(conn, team_id) -> dict:
    team = conn.execute("select * from fantasy_teams where id = %s", (team_id,)).fetchone()
    team["picks"] = conn.execute(
        """select p.athlete_id, p.role, a.display_name, a.position, a.team_id
           from fantasy_team_picks p join athletes a on a.id = p.athlete_id
           where p.fantasy_team_id = %s order by a.team_id, a.position, a.display_name""",
        (team_id,),
    ).fetchall()
    return team


@router.post("/matches/{match_id}/teams", status_code=201)
def create_team(match_id: UUID, body: TeamIn, user=Depends(current_user), conn=Depends(get_conn),
                now=Depends(utcnow)):
    match = load_match(conn, match_id)
    assert_open(match, now)
    conn.execute("select id from users where id = %s for update", (user["id"],))  # serialise per user
    labels = {r["label"] for r in conn.execute(
        "select label from fantasy_teams where user_id = %s and match_id = %s", (user["id"], match_id)).fetchall()}
    if len(labels) >= MAX_TEAMS_PER_MATCH:
        raise ApiError(409, "team_limit", f"you can have at most {MAX_TEAMS_PER_MATCH} teams per match")
    picks = _picks(body)
    _check_team(conn, match, picks)
    _check_duplicate(conn, user["id"], match_id, picks)
    label = next(f"Team {i}" for i in range(1, MAX_TEAMS_PER_MATCH + 1) if f"Team {i}" not in labels)
    team_id = conn.execute(
        "insert into fantasy_teams (user_id, match_id, label) values (%s, %s, %s) returning id",
        (user["id"], match_id, label),
    ).fetchone()["id"]
    _write_picks(conn, team_id, picks)
    return _team_out(conn, team_id)


@router.put("/teams/{team_id}")
def edit_team(team_id: UUID, body: TeamIn, user=Depends(current_user), conn=Depends(get_conn),
              now=Depends(utcnow)):
    team = conn.execute("select * from fantasy_teams where id = %s and user_id = %s for update",
                        (team_id, user["id"])).fetchone()
    if team is None:
        raise ApiError(404, "team_not_found", "team not found")
    match = load_match(conn, team["match_id"])
    assert_open(match, now)
    picks = _picks(body)
    _check_team(conn, match, picks)
    _check_duplicate(conn, user["id"], team["match_id"], picks, exclude_team_id=team_id)
    _write_picks(conn, team_id, picks)
    conn.execute("update fantasy_teams set updated_at = now() where id = %s", (team_id,))
    return _team_out(conn, team_id)


@router.get("/teams/{team_id}/breakdown")
def team_breakdown(team_id: UUID, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """Team total with every athlete's points and multiplier explained (PRD F2)."""
    team = conn.execute("select * from fantasy_teams where id = %s and user_id = %s",
                        (team_id, user["id"])).fetchone()
    if team is None:
        raise ApiError(404, "team_not_found", "team not found")
    match = load_match(conn, team["match_id"])
    scores = stream_scores(conn, match, official_or_primary_scorer(conn, match), now)
    out = _team_out(conn, team_id)
    picks = [Pick(str(p["athlete_id"]), p["role"]) for p in out["picks"]]
    total, lines = team_points(picks, scores)
    for p, (_, _, base, pts) in zip(out["picks"], lines):
        score = scores.get(str(p["athlete_id"]))
        p.update(base_points=base, points=pts,
                 breakdown=[{"label": lbl, "points": v} for lbl, v in (score.breakdown if score else [])])
    out["total_points"] = total
    out["match_status"] = match["status"]
    return out


@router.get("/me/teams")
def my_teams(match_id: UUID | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    ids = conn.execute(
        """select id from fantasy_teams where user_id = %s and (%s::uuid is null or match_id = %s)
           order by match_id, label""",
        (user["id"], match_id, match_id),
    ).fetchall()
    return [_team_out(conn, r["id"]) for r in ids]
