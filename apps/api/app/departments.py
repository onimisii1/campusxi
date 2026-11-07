"""Department pages and match previews, built from the tournament's own data (squads, fixtures,
results, scorers). A "department" is a team name within a school: CPE's football and basketball
teams are separate rows in separate tournaments but one department page."""
from app.competition import cached, player_stats, scoreline, standings
from app.errors import ApiError
from app.matches import MATCH_SQL, is_locked

POS_ORDER = {p: i for i, p in enumerate(("GK", "DEF", "MID", "FWD", "G", "F", "C", "P"))}


def _team_ref(name, colour, logo) -> dict:
    return {"name": name, "colour": colour, "logo": logo}


def _sibling_teams(conn, team_id) -> list:
    base = conn.execute("""select t.name, tr.school_id from teams t join tournaments tr on tr.id = t.tournament_id
                           where t.id = %s and tr.status = 'published'""", (team_id,)).fetchone()
    if base is None:
        raise ApiError(404, "team_not_found", "team not found")
    return conn.execute(
        """select t.id, t.name, t.colour, t.logo_url, tr.id as tournament_id, tr.name as tournament, tr.sport,
                  tr.school_id
           from teams t join tournaments tr on tr.id = t.tournament_id
           where tr.school_id = %s and lower(t.name) = lower(%s) and tr.status = 'published'
           order by case tr.sport when 'football' then 0 when 'basketball' then 1 else 2 end, tr.name""",
        (base["school_id"], base["name"])).fetchall()


def _tournament(conn, tournament_id) -> dict:
    return conn.execute("select * from tournaments where id = %s", (tournament_id,)).fetchone()


def _table_row(conn, t, team_id):
    table = cached(conn, t["id"], "standings", lambda: standings(conn, t))
    return next((r for r in table if str(r["team"]["id"]) == str(team_id)), None)


def _top_players(conn, t, team_id, n=3) -> list:
    stats = cached(conn, t["id"], "stats", lambda: player_stats(conn, t))
    return [p for p in stats["players"] if str(p["team"]["id"]) == str(team_id)][:n]


def _matches(conn, team_id, now) -> list:
    rows = conn.execute(MATCH_SQL + " where (m.home_team_id = %s or m.away_team_id = %s) order by m.scheduled_start, m.code",
                        (team_id, team_id)).fetchall()
    out = []
    for m in rows:
        home = m["home_team_id"] == team_id
        opp = _team_ref(m["away_team"], m["away_colour"], m["away_logo"]) if home else \
            _team_ref(m["home_team"], m["home_colour"], m["home_logo"])
        item = {"id": m["id"], "code": m["code"], "stage": m["stage"], "scheduled_start": m["scheduled_start"],
                "status": m["status"], "home": home, "opponent": opp, "locked": is_locked(m, now),
                "score": None, "outcome": None, "walkover": False}
        if m["status"] == "confirmed":
            r = conn.execute("select home_score, away_score, winner, walkover from match_results where match_id = %s",
                             (m["id"],)).fetchone()
            if r:
                mine, theirs = (r["home_score"], r["away_score"]) if home else (r["away_score"], r["home_score"])
                side = "home" if home else "away"
                item.update(score={"for": mine, "against": theirs}, walkover=r["walkover"],
                            outcome="D" if r["winner"] == "draw" else ("W" if r["winner"] == side else "L"))
        out.append(item)
    return out


def department(conn, team_id, now) -> dict:
    """One page per department: each sport's squad (captain marked), table place, form, results,
    next match and top performers."""
    teams = _sibling_teams(conn, team_id)
    first = next(t for t in teams if str(t["id"]) == str(team_id)) if any(
        str(t["id"]) == str(team_id) for t in teams) else teams[0]
    sports = []
    for t in teams:
        tour = _tournament(conn, t["tournament_id"])
        squad = conn.execute("""select id, display_name as name, position, is_captain from athletes
                                where team_id = %s and active order by display_name""", (t["id"],)).fetchall()
        squad.sort(key=lambda a: (not a["is_captain"], POS_ORDER.get(a["position"], 99), a["name"].lower()))
        matches = _matches(conn, t["id"], now)
        results = [m for m in matches if m["outcome"]]
        upcoming = [m for m in matches if m["status"] not in ("confirmed", "abandoned") and not m["outcome"]]
        sports.append({
            "team_id": t["id"], "sport": t["sport"], "tournament": {"id": t["tournament_id"], "name": t["tournament"]},
            "table": _table_row(conn, tour, t["id"]), "squad": squad,
            "captain": next((a["name"] for a in squad if a["is_captain"]), None),
            "results": list(reversed(results)), "next": upcoming[0] if upcoming else None, "upcoming": upcoming,
            "top_players": _top_players(conn, tour, t["id"]),
        })
    return {"name": first["name"], "colour": first["colour"], "logo": first["logo_url"],
            "school_id": first["school_id"], "sports": sports}


def preview(conn, m, now) -> dict:
    """Before a match: each side's table place and form, captain and top performers in this
    tournament, and every previous meeting of the two departments (any sport)."""
    tour = _tournament(conn, m["tournament_id"])
    sides = {}
    for side in ("home", "away"):
        tid = m[f"{side}_team_id"]
        row = _table_row(conn, tour, tid)
        captain = conn.execute("select display_name from athletes where team_id = %s and is_captain and active "
                               "order by display_name limit 1", (tid,)).fetchone()
        played = [x for x in _matches(conn, tid, now) if x["outcome"]]
        sides[side] = {"team_id": tid, "name": m[f"{side}_team"], "position": row["rank"] if row else None,
                       "shared": row.get("shared") if row else False, "points": row["points"] if row else 0,
                       "played": row["played"] if row else 0, "form": [x["outcome"] for x in played][-5:],
                       "captain": captain["display_name"] if captain else None,
                       "top_players": _top_players(conn, tour, tid, 2)}
    meetings = conn.execute(
        MATCH_SQL + """ where t.school_id = %(school)s and t.status = 'published' and m.status = 'confirmed'
             and m.id <> %(id)s and m.scheduled_start < %(start)s
             and ((lower(h.name) = lower(%(home)s) and lower(a.name) = lower(%(away)s))
               or (lower(h.name) = lower(%(away)s) and lower(a.name) = lower(%(home)s)))
           order by m.scheduled_start desc""",
        {"school": m["school_id"], "id": m["id"], "start": m["scheduled_start"],
         "home": m["home_team"], "away": m["away_team"]}).fetchall()
    return {"match_id": m["id"], "home": sides["home"], "away": sides["away"],
            "meetings": [{"id": x["id"], "sport": x["sport"], "code": x["code"], "scheduled_start": x["scheduled_start"],
                          "home": x["home_team"], "away": x["away_team"], "score": scoreline(conn, x)}
                         for x in meetings]}
