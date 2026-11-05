"""Admin setup (PRD 5.2, 8.8): schools, tournaments, squad/fixture import, line-ups, scorers, roles.

Admins manage their own school; superadmins manage every school. Every write is
recorded in the append-only audit_log.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.audit import audit
from app.auth import require_admin, require_superadmin
from app.clock import utcnow
from app.db import get_conn
from app.engines.scoring.rules import CURRENT_VERSION
from app.errors import ApiError
from app.imports import parse_fixtures, parse_squads
from app.matches import assert_open, load_match
from app.schemas import LineupIn, RolesIn, SchoolIn, ScorersIn, TournamentIn

router = APIRouter(prefix="/admin", tags=["admin"])

# Most athletes a side can start (volleyball: six on court plus the libero).
MAX_STARTERS = {"football": 11, "basketball": 5, "volleyball": 7}


def _guard_school(user: dict, school_id):
    if "superadmin" not in user["roles"] and user["school_id"] != school_id:
        raise ApiError(403, "other_school", "you can only manage your own school")


def _tournament(conn, user, tournament_id) -> dict:
    t = conn.execute("select * from tournaments where id = %s", (tournament_id,)).fetchone()
    if t is None:
        raise ApiError(404, "tournament_not_found", "tournament not found")
    _guard_school(user, t["school_id"])
    return t


async def _csv_body(request: Request) -> str:
    try:
        return (await request.body()).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(422, "bad_encoding", "upload the CSV as UTF-8")


@router.post("/schools", status_code=201)
def create_school(body: SchoolIn, user=Depends(require_superadmin), conn=Depends(get_conn)):
    if conn.execute("select 1 from schools where lower(name) = lower(%s)", (body.name,)).fetchone():
        raise ApiError(409, "school_exists", "that school already exists")
    school = conn.execute("insert into schools (name) values (%s) returning *", (body.name.strip(),)).fetchone()
    audit(conn, user["id"], "school.create", "school", school["id"], name=school["name"])
    return school


@router.get("/tournaments")
def list_tournaments(user=Depends(require_admin), conn=Depends(get_conn)):
    return conn.execute(
        """select * from tournaments where %(all)s or school_id = %(school)s
           order by created_at desc""",
        {"all": "superadmin" in user["roles"], "school": user["school_id"]},
    ).fetchall()


@router.post("/tournaments", status_code=201)
def create_tournament(body: TournamentIn, user=Depends(require_admin), conn=Depends(get_conn)):
    _guard_school(user, body.school_id)
    sport = conn.execute("select * from sports where code = %s", (body.sport,)).fetchone()
    if sport is None or not sport["live"]:
        raise ApiError(422, "sport_unavailable", f"{body.sport} is not available yet")
    if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
        raise ApiError(422, "bad_dates", "ends_on is before starts_on")
    if conn.execute("select 1 from tournaments where school_id = %s and lower(name) = lower(%s)",
                    (body.school_id, body.name)).fetchone():
        raise ApiError(409, "tournament_exists", "this school already has a tournament with that name")
    t = conn.execute(
        """insert into tournaments (school_id, sport, name, match_minutes, starts_on, ends_on)
           values (%s, %s, %s, %s, %s, %s) returning *""",
        (body.school_id, body.sport, body.name.strip(), body.match_minutes, body.starts_on, body.ends_on),
    ).fetchone()
    audit(conn, user["id"], "tournament.create", "tournament", t["id"], name=t["name"], sport=t["sport"])
    return t


@router.post("/tournaments/{tournament_id}/publish")
def publish_tournament(tournament_id: UUID, user=Depends(require_admin), conn=Depends(get_conn)):
    t = _tournament(conn, user, tournament_id)
    if not conn.execute("select 1 from matches where tournament_id = %s", (tournament_id,)).fetchone():
        raise ApiError(422, "no_fixtures", "import fixtures before publishing")
    t = conn.execute("update tournaments set status = 'published' where id = %s returning *",
                     (t["id"],)).fetchone()
    audit(conn, user["id"], "tournament.publish", "tournament", t["id"])
    return t


@router.post("/tournaments/{tournament_id}/squads")
async def import_squads(tournament_id: UUID, request: Request, user=Depends(require_admin),
                        conn=Depends(get_conn)):
    t = _tournament(conn, user, tournament_id)
    rows, errors = parse_squads(await _csv_body(request), t["sport"])
    if errors:
        raise ApiError(422, "invalid_csv", "fix these rows and upload again; nothing was imported", errors)
    teams = {r["name"].lower(): r["id"] for r in conn.execute(
        "select id, name from teams where tournament_id = %s", (t["id"],)).fetchall()}
    new_teams = new_athletes = updated = 0
    for team, athlete, position in rows:
        if team.lower() not in teams:
            teams[team.lower()] = conn.execute(
                "insert into teams (tournament_id, name) values (%s, %s) returning id", (t["id"], team)
            ).fetchone()["id"]
            new_teams += 1
        res = conn.execute(
            """insert into athletes (team_id, display_name, position) values (%s, %s, %s)
               on conflict (team_id, display_name)
               do update set position = excluded.position, active = true
               returning (xmax = 0) as inserted""",
            (teams[team.lower()], athlete, position),
        ).fetchone()
        new_athletes += res["inserted"]
        updated += not res["inserted"]
    summary = {"teams_created": new_teams, "athletes_created": new_athletes, "athletes_updated": updated}
    audit(conn, user["id"], "tournament.import_squads", "tournament", t["id"], **summary)
    return summary


@router.post("/tournaments/{tournament_id}/fixtures")
async def import_fixtures(tournament_id: UUID, request: Request, user=Depends(require_admin),
                          conn=Depends(get_conn)):
    t = _tournament(conn, user, tournament_id)
    teams = {r["name"]: r["id"] for r in conn.execute(
        "select id, name from teams where tournament_id = %s", (t["id"],)).fetchall()}
    rows, errors = parse_fixtures(await _csv_body(request), set(teams))
    if errors:
        raise ApiError(422, "invalid_csv", "fix these rows and upload again; nothing was imported", errors)
    created = 0
    for home, away, start, venue in rows:
        exists = conn.execute(
            """select 1 from matches where tournament_id = %s and home_team_id = %s and away_team_id = %s
               and scheduled_start = %s""", (t["id"], teams[home], teams[away], start)).fetchone()
        if exists:
            continue
        conn.execute(
            """insert into matches (tournament_id, home_team_id, away_team_id, venue, scheduled_start,
                                    scheduled_minutes, rules_version)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (t["id"], teams[home], teams[away], venue, start, t["match_minutes"], CURRENT_VERSION[t["sport"]]),
        )
        created += 1
    audit(conn, user["id"], "tournament.import_fixtures", "tournament", t["id"], matches_created=created)
    return {"matches_created": created, "skipped_existing": len(rows) - created}


@router.post("/matches/{match_id}/lineup")
def publish_lineup(match_id: UUID, body: LineupIn, user=Depends(require_admin), conn=Depends(get_conn),
                   now=Depends(utcnow)):
    m = load_match(conn, match_id, published_only=False)
    _guard_school(user, m["school_id"])
    assert_open(m, now)
    ids = body.starters + body.bench
    if len(set(ids)) != len(ids):
        raise ApiError(422, "duplicate_athletes", "an athlete is listed more than once")
    found = {r["id"]: r["team_id"] for r in conn.execute(
        "select id, team_id from athletes where id = any(%s) and active and team_id in (%s, %s)",
        (ids, m["home_team_id"], m["away_team_id"])).fetchall()}
    unknown = [str(a) for a in ids if a not in found]
    if unknown:
        raise ApiError(422, "unknown_athletes", "these athletes are not in either squad", unknown)
    cap = MAX_STARTERS[m["sport"]]
    for side in (m["home_team_id"], m["away_team_id"]):
        n = sum(1 for a in body.starters if found[a] == side)
        if n > cap:
            raise ApiError(422, "too_many_starters", f"a {m['sport']} side can start at most {cap} (got {n})")
    conn.execute("delete from match_lineups where match_id = %s", (match_id,))
    with conn.cursor() as cur:
        cur.executemany("insert into match_lineups (match_id, athlete_id, started) values (%s, %s, %s)",
                        [(match_id, a, True) for a in body.starters] + [(match_id, a, False) for a in body.bench])
    conn.execute("update matches set status = 'lineup_out' where id = %s", (match_id,))
    audit(conn, user["id"], "match.publish_lineup", "match", match_id,
          starters=len(body.starters), bench=len(body.bench))
    return {"match_id": match_id, "status": "lineup_out", "starters": len(body.starters), "bench": len(body.bench)}


@router.post("/matches/{match_id}/scorers")
def assign_scorers(match_id: UUID, body: ScorersIn, user=Depends(require_admin), conn=Depends(get_conn)):
    m = load_match(conn, match_id, published_only=False)
    _guard_school(user, m["school_id"])
    if len(set(body.user_ids)) != len(body.user_ids):
        raise ApiError(422, "duplicate_scorers", "the two scorers must be different people")
    scorers = conn.execute("select id from users where id = any(%s) and 'scorer' = any(roles) and school_id = %s",
                           (body.user_ids, m["school_id"])).fetchall()
    if len(scorers) != len(body.user_ids):
        raise ApiError(422, "not_scorers", "every scorer needs the scorer role at this school")
    conn.execute("delete from match_scorers where match_id = %s", (match_id,))
    for uid in body.user_ids:
        conn.execute("insert into match_scorers (match_id, user_id) values (%s, %s)", (match_id, uid))
    audit(conn, user["id"], "match.assign_scorers", "match", match_id, scorers=body.user_ids)
    return {"match_id": match_id, "scorers": body.user_ids}


@router.post("/users/{user_id}/roles")
def set_roles(user_id: UUID, body: RolesIn, user=Depends(require_admin), conn=Depends(get_conn)):
    target = conn.execute("select * from users where id = %s", (user_id,)).fetchone()
    if target is None:
        raise ApiError(404, "user_not_found", "user not found")
    _guard_school(user, target["school_id"])
    roles = sorted(set(body.roles) | {"player"})
    if {"admin", "superadmin"} & (set(roles) ^ set(target["roles"])) and "superadmin" not in user["roles"]:
        raise ApiError(403, "forbidden", "only a superadmin can grant or remove admin roles")
    updated = conn.execute("update users set roles = %s where id = %s returning id, roles",
                           (roles, user_id)).fetchone()
    audit(conn, user["id"], "user.set_roles", "user", user_id, before=target["roles"], after=roles)
    return updated
