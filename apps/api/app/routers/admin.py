"""Admin setup (PRD 5.2, 8.8): schools, tournaments, squad/fixture import, line-ups, scorers, roles.

Admins manage their own school; superadmins manage every school. Every write is
recorded in the append-only audit_log.
"""
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.audit import audit
from app.auth import require_admin, require_superadmin
from app.clock import utcnow
from app.db import get_conn
from app.engines.scoring.rules import CURRENT_VERSION, POSITIONS
from app.errors import ApiError
from app.competition import bracket
from app.imports import normalise_position, parse_fixtures, parse_result_stats, parse_results, parse_squads
from app.live import lineup_entries, stream_scores, tallies
from app.matches import IN_PLAY_STATUSES, assert_open, kick_off, load_match
from app.routers.contests import create_free_contest
from app.schemas import (AthletePatch, ConfirmIn, KnockoutIn, LineupIn, TournamentPatch, PostponeIn, ReopenIn, RolesIn, SchoolIn, ScorersIn, TournamentIn,
                         WalkoverIn)
from app.settlement import settle_free, void_match

router = APIRouter(prefix="/admin", tags=["admin"])

DISPUTE_HOLD = timedelta(hours=24)   # PRD K1: payouts wait 24h after confirmation

# A walkover has no scoreline (agreed 6 Nov 2026: it shows as voided); the winner still gets the
# league points, recorded as 0-0 with `winner` set so goal difference is untouched.

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
    rows, colours, errors = parse_squads(await _csv_body(request), t["sport"])
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
    for team_key, colour in colours.items():
        conn.execute("update teams set colour = %s where id = %s", (colour, teams[team_key]))
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
    taken = {r["code"].lower() for r in conn.execute(
        "select code from matches where tournament_id = %s and code is not null", (t["id"],)).fetchall()}
    created = 0
    for home, away, start, venue, code, stage in rows:
        exists = conn.execute(
            """select 1 from matches where tournament_id = %s and home_team_id = %s and away_team_id = %s
               and scheduled_start = %s""", (t["id"], teams[home], teams[away], start)).fetchone()
        if exists:
            continue
        if code and code.lower() in taken:
            raise ApiError(422, "invalid_csv", "fix these rows and upload again; nothing was imported",
                           [{"row": None, "message": f"match code {code} is already used in this tournament"}])
        match_id = conn.execute(
            """insert into matches (tournament_id, home_team_id, away_team_id, venue, scheduled_start,
                                    scheduled_minutes, rules_version, code, stage)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
            (t["id"], teams[home], teams[away], venue, start, t["match_minutes"], CURRENT_VERSION[t["sport"]],
             code, stage),
        ).fetchone()["id"]
        create_free_contest(conn, match_id)   # every match gets a free contest for the pilot
        created += 1
    audit(conn, user["id"], "tournament.import_fixtures", "tournament", t["id"], matches_created=created)
    return {"matches_created": created, "skipped_existing": len(rows) - created}


@router.post("/tournaments/{tournament_id}/knockout", status_code=201)
def add_knockout(tournament_id: UUID, body: KnockoutIn, user=Depends(require_admin), conn=Depends(get_conn),
                 now=Depends(utcnow)):
    """A semi-final, final or 3rd-place match. The pairs are the admin's call (the bracket endpoint
    suggests 1v4 and 2v3 from the table)."""
    t = _tournament(conn, user, tournament_id)
    teams = {r["id"] for r in conn.execute("select id from teams where tournament_id = %s", (t["id"],)).fetchall()}
    if body.home_team_id not in teams or body.away_team_id not in teams:
        raise ApiError(422, "unknown_team", "both teams must be in this tournament")
    if body.home_team_id == body.away_team_id:
        raise ApiError(422, "same_team", "a team can't play itself")
    if body.scheduled_start <= now:
        raise ApiError(422, "start_in_past", "the kick-off must be in the future")
    if body.code and conn.execute("select 1 from matches where tournament_id = %s and lower(code) = lower(%s)",
                                  (t["id"], body.code)).fetchone():
        raise ApiError(409, "code_taken", f"match code {body.code} is already used in this tournament")
    m = conn.execute(
        """insert into matches (tournament_id, home_team_id, away_team_id, venue, scheduled_start,
                                scheduled_minutes, rules_version, code, stage)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id, code, stage, scheduled_start""",
        (t["id"], body.home_team_id, body.away_team_id, body.venue, body.scheduled_start, t["match_minutes"],
         CURRENT_VERSION[t["sport"]], body.code, body.stage)).fetchone()
    create_free_contest(conn, m["id"])
    audit(conn, user["id"], "tournament.add_knockout", "tournament", t["id"], match_id=m["id"], stage=body.stage)
    return {**m, "bracket": bracket(conn, t)}


@router.post("/tournaments/{tournament_id}/results")
async def import_results(tournament_id: UUID, request: Request, user=Depends(require_admin),
                         conn=Depends(get_conn), now=Depends(utcnow)):
    """Results from before the app was used: confirmed matches with no contests or fantasy play."""
    t = _tournament(conn, user, tournament_id)
    teams = {r["name"]: r["id"] for r in conn.execute(
        "select id, name from teams where tournament_id = %s", (t["id"],)).fetchall()}
    rows, errors = parse_results(await _csv_body(request), set(teams), t["sport"])
    taken = {r["code"].lower() for r in conn.execute(
        "select code from matches where tournament_id = %s and code is not null", (t["id"],)).fetchall()}
    errors += [{"row": None, "message": f"match code {r[0]} is already used in this tournament"}
               for r in rows if r[0].lower() in taken]
    if errors:
        raise ApiError(422, "invalid_csv", "fix these rows and upload again; nothing was imported", errors)
    for code, home, away, hs, aws, played, venue in rows:
        m = conn.execute(
            """insert into matches (tournament_id, home_team_id, away_team_id, venue, scheduled_start, kicked_off_at,
                                    scheduled_minutes, rules_version, code, status)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed') returning id""",
            (t["id"], teams[home], teams[away], venue, played, played, t["match_minutes"],
             CURRENT_VERSION[t["sport"]], code)).fetchone()
        winner = "draw" if hs == aws else ("home" if hs > aws else "away")
        conn.execute(
            """insert into match_results (match_id, home_score, away_score, winner, confirmed_by, confirmed_at,
                                          official_scorer_id, imported)
               values (%s, %s, %s, %s, %s, %s, %s, true)""",
            (m["id"], hs, aws, winner, user["id"], now, user["id"]))
    audit(conn, user["id"], "tournament.import_results", "tournament", t["id"], results=len(rows))
    return {"results_imported": len(rows)}


@router.post("/tournaments/{tournament_id}/result-stats")
async def import_result_stats(tournament_id: UUID, request: Request, user=Depends(require_admin),
                              conn=Depends(get_conn)):
    """Stat lines for imported results (goals/assists, or basketball box scores). They are recorded as
    the importing admin's stat stream, which is the official stream for those matches."""
    t = _tournament(conn, user, tournament_id)
    rows, errors = parse_result_stats(await _csv_body(request), t["sport"])
    matches = {r["code"].lower(): r for r in conn.execute(
        """select m.id, m.code, m.home_team_id, m.away_team_id, r.official_scorer_id
           from matches m join match_results r on r.match_id = m.id
           where m.tournament_id = %s and r.imported""", (t["id"],)).fetchall()}
    athletes = {(r["team"].lower(), r["display_name"].lower()): r for r in conn.execute(
        """select a.id, a.team_id, a.display_name, t.name as team from athletes a join teams t on t.id = a.team_id
           where t.tournament_id = %s""", (t["id"],)).fetchall()}
    resolved = []
    for row, (code, team, athlete, counts) in rows:
        m, a = matches.get(code.lower()), athletes.get((team.lower(), athlete.lower()))
        if m is None:
            errors.append({"row": row, "message": f"no imported result with code {code!r} (import results first)"})
        elif a is None:
            errors.append({"row": row, "message": f"{athlete!r} isn't in the {team} squad"})
        elif a["team_id"] not in (m["home_team_id"], m["away_team_id"]):
            errors.append({"row": row, "message": f"{team} didn't play {code}"})
        elif conn.execute("select 1 from stat_events where match_id = %s and athlete_id = %s",
                          (m["id"], a["id"])).fetchone():
            errors.append({"row": row, "message": f"{athlete} already has stats for {code}"})
        else:
            resolved.append((m, a, counts))
    if errors:
        raise ApiError(422, "invalid_csv", "fix these rows and upload again; nothing was imported", errors)
    events = 0
    for m, a, counts in resolved:
        conn.execute("""insert into match_lineups (match_id, athlete_id, started) values (%s, %s, true)
                        on conflict do nothing""", (m["id"], a["id"]))
        seq = conn.execute("select coalesce(max(client_seq), 0) as s from stat_events where match_id = %s and "
                           "scorer_id = %s", (m["id"], m["official_scorer_id"])).fetchone()["s"]
        for etype, amount in counts.items():
            # One event per stat carrying the count; timed football events get minute 0 (unknown).
            seq += 1
            conn.execute(
                """insert into stat_events (match_id, scorer_id, athlete_id, event_type, minute, amount, client_seq)
                   values (%s, %s, %s, %s, %s, %s, %s)""",
                (m["id"], m["official_scorer_id"], a["id"], etype, 0 if t["sport"] == "football" else None,
                 amount, seq))
            events += 1
    audit(conn, user["id"], "tournament.import_result_stats", "tournament", t["id"], stat_lines=len(resolved))
    return {"stat_lines": len(resolved), "events": events}


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
    if conn.execute("select 1 from stat_events where match_id = %s", (match_id,)).fetchone():
        raise ApiError(409, "scoring_started", "scorers can't be changed once events are recorded")
    conn.execute("delete from match_scorers where match_id = %s", (match_id,))
    # The first scorer is primary: their stream drives live points.
    for uid, role in zip(body.user_ids, ("primary", "secondary")):
        conn.execute("insert into match_scorers (match_id, user_id, role) values (%s, %s, %s)",
                     (match_id, uid, role))
    audit(conn, user["id"], "match.assign_scorers", "match", match_id, scorers=body.user_ids)
    return {"match_id": match_id, "scorers": body.user_ids}


def _admin_match(conn, user, match_id) -> dict:
    m = load_match(conn, match_id, published_only=False)
    _guard_school(user, m["school_id"])
    conn.execute("select id from matches where id = %s for update", (match_id,))
    return m


@router.get("/matches/{match_id}/reconcile")
def reconcile(match_id: UUID, user=Depends(require_admin), conn=Depends(get_conn)):
    """Side-by-side scorer streams: every tally or points difference, plus reported scores."""
    m = _admin_match(conn, user, match_id)
    scorers = conn.execute(
        """select s.user_id, s.role, u.team_name, x.home_score, x.away_score, x.shootout_winner,
                  x.submitted_at
           from match_scorers s join users u on u.id = s.user_id
           left join stat_submissions x on x.match_id = s.match_id and x.scorer_id = s.user_id
           where s.match_id = %s order by s.role""", (match_id,)).fetchall()
    names = {str(r["athlete_id"]): r["display_name"] for r in lineup_entries(conn, m)}
    streams = {}
    for s in scorers:
        streams[s["role"]] = {"tallies": tallies(conn, match_id, s["user_id"]),
                              "points": {a: sc.points for a, sc in stream_scores(conn, m, s["user_id"]).items()}}
    mismatches, point_diffs = [], []
    if len(streams) == 2:
        p, q = streams["primary"], streams["secondary"]
        for key in sorted(set(p["tallies"]) | set(q["tallies"])):
            if p["tallies"][key] != q["tallies"][key]:
                mismatches.append({"athlete_id": key[0], "athlete": names.get(key[0]), "event_type": key[1],
                                   "primary": p["tallies"][key], "secondary": q["tallies"][key]})
        for a in sorted(names):
            if p["points"].get(a) != q["points"].get(a):
                point_diffs.append({"athlete_id": a, "athlete": names[a],
                                    "primary": p["points"].get(a), "secondary": q["points"].get(a)})
    reported = {(s["home_score"], s["away_score"], s["shootout_winner"]) for s in scorers if s["submitted_at"]}
    return {
        "match_id": match_id, "status": m["status"],
        "scorers": [{k: s[k] for k in ("user_id", "role", "team_name", "home_score", "away_score",
                                         "shootout_winner", "submitted_at")} for s in scorers],
        "event_mismatches": mismatches, "points_differences": point_diffs,
        "agreed": len(scorers) == 2 and all(s["submitted_at"] for s in scorers)
                  and not mismatches and not point_diffs and len(reported) == 1,
    }


@router.post("/matches/{match_id}/reopen")
def reopen_submission(match_id: UUID, body: ReopenIn, user=Depends(require_admin), conn=Depends(get_conn)):
    m = _admin_match(conn, user, match_id)
    if m["status"] not in ("live", "final_pending"):
        raise ApiError(409, "cannot_reopen", f"this match is {m['status']}")
    gone = conn.execute("delete from stat_submissions where match_id = %s and scorer_id = %s returning id",
                        (match_id, body.scorer_id)).fetchone()
    if gone is None:
        raise ApiError(404, "no_submission", "that scorer hasn't submitted this match")
    conn.execute("update matches set status = 'live' where id = %s", (match_id,))
    audit(conn, user["id"], "match.reopen_submission", "match", match_id, scorer_id=body.scorer_id)
    return {"match_id": match_id, "status": "live"}


@router.post("/matches/{match_id}/confirm")
def confirm_result(match_id: UUID, body: ConfirmIn, user=Depends(require_admin), conn=Depends(get_conn),
                   now=Depends(utcnow)):
    m = _admin_match(conn, user, match_id)
    if m["status"] != "final_pending":
        raise ApiError(409, "not_ready", "every assigned scorer must submit before the result is confirmed")
    if not conn.execute("select 1 from stat_submissions where match_id = %s and scorer_id = %s",
                        (match_id, body.official_scorer_id)).fetchone():
        raise ApiError(422, "not_official_scorer", "the official stream must come from an assigned scorer "
                                                   "who has submitted")
    if body.home_score == body.away_score:
        winner = "draw"
    else:
        winner = "home" if body.home_score > body.away_score else "away"
    if body.shootout_winner and winner != "draw":
        raise ApiError(422, "shootout_needs_draw", "a shoot-out winner only applies to a drawn match")
    if winner == "draw" and m["sport"] != "football":
        raise ApiError(422, "no_draws", f"{m['sport']} matches can't end in a draw")
    conn.execute(
        """insert into match_results (match_id, home_score, away_score, winner, shootout_winner, confirmed_by,
                                      confirmed_at, official_scorer_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (match_id, body.home_score, body.away_score, winner, body.shootout_winner, user["id"], now,
         body.official_scorer_id),
    )
    conn.execute("update matches set status = 'confirmed' where id = %s", (match_id,))
    settle_free(conn, m, body.official_scorer_id, now)
    audit(conn, user["id"], "match.confirm", "match", match_id, score=f"{body.home_score}-{body.away_score}",
          official_scorer_id=body.official_scorer_id)
    return {"match_id": match_id, "status": "confirmed", "winner": winner, "shootout_winner": body.shootout_winner,
            "confirmed_at": now, "payout_after": now + DISPUTE_HOLD}


@router.post("/matches/{match_id}/kickoff")
def admin_kickoff(match_id: UUID, user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    """Start the match clock now (matches rarely start on the dot); see app/matches.py."""
    m = _admin_match(conn, user, match_id)
    result = kick_off(conn, m, now)
    audit(conn, user["id"], "match.kickoff", "match", match_id)
    return result


@router.post("/matches/{match_id}/walkover")
def walkover(match_id: UUID, body: WalkoverIn, user=Depends(require_admin), conn=Depends(get_conn),
             now=Depends(utcnow)):
    """A side didn't turn up: the other wins the league points; fantasy and challenges are void."""
    m = _admin_match(conn, user, match_id)
    if m["status"] not in IN_PLAY_STATUSES + ("postponed",):
        raise ApiError(409, "cannot_walkover", f"this match is {m['status']}")
    home = away = 0
    conn.execute(
        """insert into match_results (match_id, home_score, away_score, winner, confirmed_by, confirmed_at, walkover)
           values (%s, %s, %s, %s, %s, %s, true)""", (match_id, home, away, body.winner, user["id"], now))
    conn.execute("update matches set status = 'confirmed' where id = %s", (match_id,))
    void_match(conn, match_id, now)
    audit(conn, user["id"], "match.walkover", "match", match_id, winner=body.winner)
    return {"match_id": match_id, "status": "confirmed", "walkover": True, "winner": body.winner,
            "home_score": home, "away_score": away}


@router.post("/matches/{match_id}/abandon")
def abandon(match_id: UUID, user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    m = _admin_match(conn, user, match_id)
    if m["status"] in ("confirmed", "abandoned"):
        raise ApiError(409, "cannot_abandon", f"this match is already {m['status']}")
    conn.execute("update matches set status = 'abandoned' where id = %s", (match_id,))
    void_match(conn, match_id, now)
    audit(conn, user["id"], "match.abandon", "match", match_id, previous_status=m["status"])
    return {"match_id": match_id, "status": "abandoned"}


@router.post("/matches/{match_id}/postpone")
def postpone(match_id: UUID, body: PostponeIn, user=Depends(require_admin), conn=Depends(get_conn),
             now=Depends(utcnow)):
    """With new_start: reschedule (teams unlock until then). Without: hold as postponed (locked)."""
    m = _admin_match(conn, user, match_id)
    if m["status"] not in ("scheduled", "lineup_out", "postponed"):
        raise ApiError(409, "cannot_postpone", f"a {m['status']} match can't be postponed; abandon it instead")
    if body.new_start is not None and body.new_start <= now:
        raise ApiError(422, "start_in_past", "the new start must be in the future")
    status = "postponed" if body.new_start is None else ("lineup_out" if m["status"] == "lineup_out" else "scheduled")
    conn.execute(
        """update matches set status = %s, scheduled_start = coalesce(%s, scheduled_start),
                  original_start = coalesce(original_start, scheduled_start) where id = %s""",
        (status, body.new_start, match_id),
    )
    audit(conn, user["id"], "match.postpone", "match", match_id, new_start=body.new_start)
    return {"match_id": match_id, "status": status, "scheduled_start": body.new_start or m["scheduled_start"]}


@router.get("/tournaments/{tournament_id}/matches")
def admin_matches(tournament_id: UUID, user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    """Every match in a tournament (published or not) with what the admin still has to do."""
    t = _tournament(conn, user, tournament_id)
    rows = conn.execute(
        """select m.id, m.code, m.stage, m.status, m.scheduled_start, m.kicked_off_at, m.venue,
                  h.name as home_team, a.name as away_team, h.colour as home_colour, a.colour as away_colour,
                  r.home_score, r.away_score, r.walkover, r.imported,
                  (select count(*) from match_lineups l where l.match_id = m.id and l.started) as starters,
                  (select count(*) from match_scorers s where s.match_id = m.id) as scorers,
                  (select count(*) from stat_submissions x where x.match_id = m.id) as submissions
           from matches m join teams h on h.id = m.home_team_id join teams a on a.id = m.away_team_id
           left join match_results r on r.match_id = m.id
           where m.tournament_id = %s order by m.scheduled_start, m.code""", (t["id"],)).fetchall()
    return {"tournament": {k: t[k] for k in ("id", "name", "sport", "status", "match_minutes")},
            "now": now, "matches": rows}


@router.get("/users")
def school_users(role: str | None = None, user=Depends(require_admin), conn=Depends(get_conn)):
    """People at the admin's school, e.g. ?role=scorer for the scorer picker."""
    return conn.execute(
        """select id, team_name, roles from users where school_id = %s and (%s::text is null or %s = any(roles))
           order by team_name""", (user["school_id"], role, role)).fetchall()


@router.patch("/tournaments/{tournament_id}")
def update_tournament(tournament_id: UUID, body: TournamentPatch, user=Depends(require_admin), conn=Depends(get_conn)):
    """Change the match length; matches that haven't started yet follow it."""
    t = _tournament(conn, user, tournament_id)
    conn.execute("update tournaments set match_minutes = %s where id = %s", (body.match_minutes, t["id"]))
    changed = conn.execute(
        """update matches set scheduled_minutes = %s where tournament_id = %s and status in ('scheduled', 'lineup_out')
           and kicked_off_at is null returning id""", (body.match_minutes, t["id"])).fetchall()
    audit(conn, user["id"], "tournament.update", "tournament", t["id"], match_minutes=body.match_minutes,
          before=t["match_minutes"], matches_updated=len(changed))
    return {"id": t["id"], "match_minutes": body.match_minutes, "matches_updated": len(changed)}


@router.get("/tournaments/{tournament_id}/squads")
def admin_squads(tournament_id: UUID, user=Depends(require_admin), conn=Depends(get_conn)):
    """Every athlete by team, for auditing names and positions."""
    t = _tournament(conn, user, tournament_id)
    rows = conn.execute(
        """select a.id, a.display_name, a.position, a.active, tm.id as team_id, tm.name as team,
                  exists (select 1 from match_lineups l join matches m on m.id = l.match_id
                          where l.athlete_id = a.id and m.status in ('live', 'final_pending', 'confirmed')) as has_played
           from athletes a join teams tm on tm.id = a.team_id where tm.tournament_id = %s
           order by tm.name, a.position, a.display_name""", (t["id"],)).fetchall()
    return {"sport": t["sport"], "positions": sorted(POSITIONS[t["sport"]]), "athletes": rows}


@router.patch("/athletes/{athlete_id}")
def update_athlete(athlete_id: UUID, body: AthletePatch, user=Depends(require_admin), conn=Depends(get_conn)):
    """Fix a name or position, or retire an athlete. Positions are fixed once the athlete has played,
    because past points depend on them."""
    a = conn.execute(
        """select a.*, tr.school_id, tr.sport from athletes a join teams tm on tm.id = a.team_id
           join tournaments tr on tr.id = tm.tournament_id where a.id = %s for update of a""",
        (athlete_id,)).fetchone()
    if a is None:
        raise ApiError(404, "athlete_not_found", "athlete not found")
    _guard_school(user, a["school_id"])
    changes = {}
    if body.display_name is not None and body.display_name.strip() != a["display_name"]:
        name = body.display_name.strip()
        if conn.execute("select 1 from athletes where team_id = %s and lower(display_name) = lower(%s) and id <> %s",
                        (a["team_id"], name, athlete_id)).fetchone():
            raise ApiError(409, "name_taken", f"{name} is already in this squad")
        changes["display_name"] = name
    if body.position is not None:
        pos = normalise_position(a["sport"], body.position)
        if pos is None:
            raise ApiError(422, "bad_position", f"{body.position!r} isn't a {a['sport']} position")
        if pos != a["position"]:
            if conn.execute(
                    """select 1 from match_lineups l join matches m on m.id = l.match_id where l.athlete_id = %s
                       and m.status in ('live', 'final_pending', 'confirmed')""", (athlete_id,)).fetchone():
                raise ApiError(409, "already_played", "positions are fixed once a player has played: "
                                                      "past points depend on them")
            changes["position"] = pos
    if body.active is not None and body.active != a["active"]:
        changes["active"] = body.active
    if changes:
        sets = ", ".join(f"{k} = %s" for k in changes)
        conn.execute(f"update athletes set {sets} where id = %s", (*changes.values(), athlete_id))  # noqa: S608
        audit(conn, user["id"], "athlete.update", "athlete", athlete_id,
              before={k: a[k] for k in changes}, after=changes)
    row = conn.execute("select id, display_name, position, active from athletes where id = %s",
                       (athlete_id,)).fetchone()
    return {**row, "changed": sorted(changes)}



@router.get("/attention")
def needs_attention(user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    """Matches that should have finished (3h after kick-off with no confirmed result)."""
    return conn.execute(
        """select m.id, m.code, m.status, m.scheduled_start, m.tournament_id, h.name as home_team, a.name as away_team
           from matches m join tournaments t on t.id = m.tournament_id
           join teams h on h.id = m.home_team_id join teams a on a.id = m.away_team_id
           where m.status in ('scheduled', 'lineup_out', 'live', 'final_pending')
             and coalesce(m.kicked_off_at, m.scheduled_start) < %s - interval '3 hours'
             and (%s or t.school_id = %s) order by m.scheduled_start""",
        (now, "superadmin" in user["roles"], user["school_id"])).fetchall()


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
