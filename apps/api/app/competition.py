"""Tournament views built from confirmed results: league table, golden boot / MVP, bracket.

League points (NUESA 2026/27 posters): football W3 D1 L0, ranked by points, goal difference,
goals scored; basketball W2 L0, ranked by points, points difference, points scored. Teams level on
every tiebreak share a rank, shown as "2=" on the posters.
"""
from collections import Counter, defaultdict
from decimal import Decimal

from app.engines.scoring.rules import BASKETBALL, FOOTBALL
from app.live import lineup_entries, official_or_primary_scorer, tallies

LEAGUE_POINTS = {FOOTBALL: {"W": 3, "D": 1, "L": 0}, BASKETBALL: {"W": 2, "D": 1, "L": 0}}
DEFAULT_POINTS = {"W": 3, "D": 1, "L": 0}
MVP_WEIGHTS = {"point": Decimal(1), "rebound": Decimal("1.2"), "assist": Decimal("1.5"),
               "steal": Decimal("2.5"), "block": Decimal(2)}
SEMI_PAIRS = ((1, 4), (2, 3))     # suggestion only; the admin picks the real pairs


def _results(conn, tournament_id, stage="league"):
    return conn.execute(
        """select m.id, m.code, m.home_team_id, m.away_team_id, m.scheduled_start, coalesce(m.kicked_off_at,
                  m.scheduled_start) as played_at, r.home_score, r.away_score, r.winner, r.walkover,
                  r.official_scorer_id
           from matches m join match_results r on r.match_id = m.id
           where m.tournament_id = %s and m.status = 'confirmed' and (%s::text is null or m.stage = %s)
           order by played_at, m.code""", (tournament_id, stage, stage)).fetchall()


def standings(conn, tournament: dict) -> list:
    pts = LEAGUE_POINTS.get(tournament["sport"], DEFAULT_POINTS)
    teams = conn.execute("select id, name, colour from teams where tournament_id = %s",
                         (tournament["id"],)).fetchall()
    rows = {t["id"]: {"team": {"id": t["id"], "name": t["name"], "colour": t["colour"]},
                      "played": 0, "won": 0, "drawn": 0, "lost": 0, "for": 0, "against": 0,
                      "points": 0, "form": []} for t in teams}
    for r in _results(conn, tournament["id"]):
        for side, team, scored, conceded in (("home", r["home_team_id"], r["home_score"], r["away_score"]),
                                             ("away", r["away_team_id"], r["away_score"], r["home_score"])):
            row = rows[team]
            outcome = "D" if r["winner"] == "draw" else ("W" if r["winner"] == side else "L")
            row["played"] += 1
            row[{"W": "won", "D": "drawn", "L": "lost"}[outcome]] += 1
            row["for"] += scored
            row["against"] += conceded
            row["points"] += pts[outcome]
            row["form"].append(outcome)
    out = list(rows.values())
    for row in out:
        row["difference"] = row["for"] - row["against"]
        row["form"] = row["form"][-5:]
    key = lambda r: (r["points"], r["difference"], r["for"])  # noqa: E731
    out.sort(key=lambda r: (*(-k for k in key(r)), r["team"]["name"].lower()))
    for row in out:
        level = [o for o in out if key(o) == key(row)]
        row["rank"] = 1 + sum(1 for o in out if key(o) > key(row))
        row["shared"] = len(level) > 1
    return out


def scoreline(conn, match: dict) -> dict | None:
    """{'home', 'away', 'walkover', 'final'}: the confirmed result, or the live score from the
    primary scorer's stream (football goals and own goals; basketball points); None before kick-off."""
    r = conn.execute("select home_score, away_score, walkover from match_results where match_id = %s",
                     (match["id"],)).fetchone()
    if r:
        return {"home": r["home_score"], "away": r["away_score"], "walkover": r["walkover"], "final": True}
    if match["status"] not in ("live", "final_pending"):
        return None
    scorer = official_or_primary_scorer(conn, match)
    side = {str(e["athlete_id"]): ("home" if e["team_id"] == match["home_team_id"] else "away")
            for e in lineup_entries(conn, match)}
    score = {"home": 0, "away": 0}
    for (athlete, etype), amount in (tallies(conn, match["id"], scorer) if scorer else {}).items():
        if athlete not in side:
            continue
        if etype in ("goal", "point"):
            score[side[athlete]] += amount
        elif etype == "own_goal":
            score["away" if side[athlete] == "home" else "home"] += amount
    return {**score, "walkover": False, "final": False}


def _appearances(conn, match_ids) -> Counter:
    """Matches each athlete took part in: started, came on, or has a stat line."""
    rows = conn.execute(
        """select athlete_id, count(distinct match_id) as n from (
             select l.athlete_id, l.match_id from match_lineups l
             where l.match_id = any(%(m)s) and (l.started or exists (
               select 1 from stat_events e where e.match_id = l.match_id and e.athlete_id = l.athlete_id
                 and e.event_type = 'sub_on'))
             union
             select e.athlete_id, e.match_id from stat_events e
             join match_results r on r.match_id = e.match_id and r.official_scorer_id = e.scorer_id
             where e.match_id = any(%(m)s)) x group by athlete_id""", {"m": match_ids}).fetchall()
    return Counter({str(r["athlete_id"]): r["n"] for r in rows})


def player_stats(conn, tournament: dict) -> dict:
    """Golden boot (football: goals, then assists, then fewer matches) or MVP (basketball)."""
    played = [r for r in _results(conn, tournament["id"], None) if not r["walkover"] and r["official_scorer_id"]]
    totals = defaultdict(Counter)
    for r in played:
        for (athlete, etype), amount in tallies(conn, r["id"], r["official_scorer_id"]).items():
            totals[athlete][etype] += amount
    apps = _appearances(conn, [r["id"] for r in played])
    athletes = {str(a["id"]): a for a in conn.execute(
        """select a.id, a.display_name, a.position, t.id as team_id, t.name as team, t.colour
           from athletes a join teams t on t.id = a.team_id where t.tournament_id = %s""",
        (tournament["id"],)).fetchall()}

    def person(aid):
        a = athletes[aid]
        return {"athlete_id": aid, "name": a["display_name"], "position": a["position"],
                "team": {"id": a["team_id"], "name": a["team"], "colour": a["colour"]}, "matches": apps[aid]}

    if tournament["sport"] == BASKETBALL:
        rows = []
        for aid, c in totals.items():
            if aid not in athletes:
                continue
            gp = max(apps[aid], 1)
            line = {"points": c["point"], "rebounds": c["rebound"], "assists": c["assist"],
                    "steals": c["steal"], "blocks": c["block"]}
            total = sum(MVP_WEIGHTS[e] * c[e] for e in MVP_WEIGHTS)
            rows.append({**person(aid), **line, "total": total, "average": (total / gp).quantize(Decimal("0.1"))})
        rows.sort(key=lambda r: (-r["total"], r["name"].lower()))
        _rank(rows, lambda r: r["total"])
        return {"kind": "mvp", "weights": {k: str(v) for k, v in MVP_WEIGHTS.items()}, "players": rows}

    rows = [{**person(aid), "goals": c["goal"], "assists": c["assist"]}
            for aid, c in totals.items() if aid in athletes and (c["goal"] or c["assist"])]
    rows.sort(key=lambda r: (-r["goals"], -r["assists"], r["matches"], r["name"].lower()))
    _rank(rows, lambda r: (r["goals"], r["assists"], -r["matches"]))
    return {"kind": "golden_boot", "players": rows}


def _rank(rows, key):
    for row in rows:
        level = [o for o in rows if key(o) == key(row)]
        row["rank"] = 1 + sum(1 for o in rows if key(o) > key(row))
        row["shared"] = len(level) > 1


def bracket(conn, tournament: dict) -> dict:
    """Semis and final as they stand; unknown slots are labelled ("Winner SF1", "2nd in table")."""
    ko = conn.execute(
        """select m.id, m.code, m.stage, m.scheduled_start, m.status, h.name as home, a.name as away,
                  r.home_score, r.away_score, r.winner, r.shootout_winner
           from matches m join teams h on h.id = m.home_team_id join teams a on a.id = m.away_team_id
           left join match_results r on r.match_id = m.id
           where m.tournament_id = %s and m.stage <> 'league' order by m.scheduled_start, m.code""",
        (tournament["id"],)).fetchall()

    def tie(m):
        winner = None
        if m["winner"]:
            side = m["shootout_winner"] or m["winner"]
            winner = m["home"] if side == "home" else m["away"]
        return {"match_id": m["id"], "code": m["code"], "scheduled_start": m["scheduled_start"],
                "status": m["status"], "home": m["home"], "away": m["away"], "home_score": m["home_score"],
                "away_score": m["away_score"], "winner": winner, "placeholder": False}

    table = standings(conn, tournament)
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
    semis = [tie(m) for m in ko if m["stage"] == "semi"]
    if not semis:
        semis = [{"code": f"SF{i}", "placeholder": True,
                  "home": f"{ordinal[a]} in table", "away": f"{ordinal[b]} in table",
                  "projected": [table[a - 1]["team"]["name"] if len(table) >= a else None,
                                table[b - 1]["team"]["name"] if len(table) >= b else None]}
                 for i, (a, b) in enumerate(SEMI_PAIRS, start=1)]
    finals = [tie(m) for m in ko if m["stage"] == "final"]
    if not finals:
        labels = [s.get("winner") or f"Winner {s['code'] or f'SF{i}'}" for i, s in enumerate(semis[:2], start=1)]
        labels += [f"Winner SF{i}" for i in range(len(labels) + 1, 3)]   # second semi not added yet
        finals = [{"code": "F", "placeholder": True, "home": labels[0], "away": labels[1]}]
    return {"semis": semis, "final": finals[0], "third_place": next(
        (tie(m) for m in ko if m["stage"] == "third_place"), None),
        "suggested_semis": [[table[a - 1]["team"] if len(table) >= a else None,
                             table[b - 1]["team"] if len(table) >= b else None] for a, b in SEMI_PAIRS]}
