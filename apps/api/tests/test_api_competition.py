"""Running a real competition (NUESA 2026/27): kick-off, walkovers, match codes, positionless basketball."""
from datetime import timedelta

from tests.conftest import auth, fixtures_csv, make_school, make_user, valid_picks
from tests.test_api_pilot import _free_contest, _team
from tests.test_api_scorer import ev, post, sw  # noqa: F401  (sw is a fixture)


def _contest_card(client, mid, cid, user):
    return next(x for x in client.get(f"/matches/{mid}/contests", headers=auth(user)).json() if x["id"] == cid)


# ---------- kick off now ----------

def test_late_kickoff_restarts_the_clock(sw, client, db):
    """Kick-off 25 minutes late: the late-join window is measured from the real kick-off."""
    mid, n = sw["match"]["id"], sw["names"]
    late = make_user(db, sw["school"], team_name="late_fan")
    c = _free_contest(client, mid)
    team = _team(client, late, mid, valid_picks(n))

    client.clock.now = sw["kickoff"] + timedelta(minutes=25)       # past the deadline, not started
    card = _contest_card(client, mid, c["id"], late)
    assert card["locked"] and card["late_join"]["minute"] == 0       # the clock stands still before kick-off

    assert client.post(f"/admin/matches/{mid}/kickoff", headers=auth(sw["admin"])).status_code == 200
    client.clock.now = sw["kickoff"] + timedelta(minutes=25 + 50)   # 50 minutes after the real kick-off
    card = _contest_card(client, mid, c["id"], late)
    assert card["late_join"] == {"until_minute": 60, "minute": 50, "entry_fee_kobo": 0}
    assert client.post(f"/contests/{c['id']}/entries", headers=auth(late),
                       json={"fantasy_team_id": team}).status_code == 201

    client.clock.now = sw["kickoff"] + timedelta(minutes=25 + 61)
    assert _contest_card(client, mid, c["id"], late)["late_join"] is None


def test_without_a_kickoff_tap_the_clock_runs_from_the_scheduled_time(sw, client, db):
    mid = sw["match"]["id"]
    c = _free_contest(client, mid)
    client.clock.now = sw["kickoff"] + timedelta(minutes=45)        # past the 30-minute grace
    assert _contest_card(client, mid, c["id"], sw["player"])["late_join"]["minute"] == 45


def test_kickoff_rules(sw, client, db):
    mid = sw["match"]["id"]
    client.clock.now = sw["kickoff"] - timedelta(minutes=40)
    assert client.post(f"/admin/matches/{mid}/kickoff", headers=auth(sw["admin"])).json()["error"]["code"] \
        == "too_early"
    assert client.post(f"/admin/matches/{mid}/kickoff", headers=auth(sw["player"])).status_code == 403

    client.clock.now = sw["kickoff"] - timedelta(minutes=5)        # an early start locks teams at once
    res = client.post(f"/scorer/matches/{mid}/kickoff", headers=auth(sw["s1"]))
    assert res.status_code == 200 and res.json()["status"] == "live"
    assert client.get(f"/matches/{mid}").json()["locked"] is True
    assert client.post(f"/admin/matches/{mid}/kickoff", headers=auth(sw["admin"])).json()["error"]["code"] \
        == "already_kicked_off"
    other = make_user(db, sw["school"], roles=("player", "scorer"), team_name="not_assigned")
    assert client.post(f"/scorer/matches/{mid}/kickoff", headers=auth(other)).status_code == 403


# ---------- walkover ----------

def test_walkover_voids_fantasy_and_counts_in_the_league(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    c = _free_contest(client, mid)
    team = _team(client, sw["player"], mid, valid_picks(n))
    client.post(f"/contests/{c['id']}/entries", headers=auth(sw["player"]), json={"fantasy_team_id": team})

    client.clock.now = sw["kickoff"] + timedelta(minutes=12)
    res = client.post(f"/admin/matches/{mid}/walkover", headers=auth(sw["admin"]), json={"winner": "away"})
    assert res.status_code == 200
    assert (res.json()["home_score"], res.json()["away_score"], res.json()["walkover"]) == (0, 3, True)
    assert db.execute("select status from contests where id = %s", (c["id"],)).fetchone()["status"] == "cancelled"
    assert client.get(f"/matches/{mid}").json()["status"] == "confirmed"
    season = client.get(f"/tournaments/{sw['tournament']['id']}/leaderboard").json()
    assert season["entries"] == []                                   # no fantasy play to count
    again = client.post(f"/admin/matches/{mid}/walkover", headers=auth(sw["admin"]), json={"winner": "home"})
    assert again.json()["error"]["code"] == "cannot_walkover"


# ---------- fixtures with codes and stages ----------

def _tournament(client, db, sport="football", squads=None):
    school = make_school(db, f"Nile {sport}")
    admin = make_user(db, school, roles=("player", "admin"))
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": sport, "name": "NUESA 2026/27", "match_minutes": 30}).json()
    if squads:
        assert client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin), content=squads).status_code == 200
    return t, admin


def test_fixture_codes_and_stages(client, db):
    from tests.conftest import football_squads_csv
    t, admin = _tournament(client, db, squads=football_squads_csv())
    url = f"/admin/tournaments/{t['id']}/fixtures"
    body = ("home_team,away_team,scheduled_start,venue,code,stage\n"
            "Engineering,Law,2026-11-12T16:00:00,Pitch,M4,\n"
            "Medicine,Sciences,2026-11-12T16:40:00,Pitch,SF1,Semi-final\n")
    assert client.post(url, headers=auth(admin), content=body).json()["matches_created"] == 2
    rows = db.execute("select code, stage from matches where tournament_id = %s order by code", (t["id"],)).fetchall()
    assert [(r["code"], r["stage"]) for r in rows] == [("M4", "league"), ("SF1", "semi")]

    bad = ("home_team,away_team,scheduled_start,venue,code,stage\n"
           "Engineering,Medicine,2026-11-19T16:00:00,Pitch,M9,group\n"
           "Law,Sciences,2026-11-19T16:40:00,Pitch,M9,\n")
    err = client.post(url, headers=auth(admin), content=bad).json()["error"]
    assert [d["row"] for d in err["details"]] == [2, 3]
    reused = client.post(url, headers=auth(admin), content=fixtures_csv([("Law", "Medicine", "2026-11-20T16:00:00", "P")])
                         .replace("venue\n", "venue,code\n").replace(",P\n", ",P,m4\n"))
    assert reused.json()["error"]["code"] == "invalid_csv"
    assert db.execute("select count(*) as n from matches where tournament_id = %s", (t["id"],)).fetchone()["n"] == 2


# ---------- positionless basketball ----------

def test_positionless_basketball_squads_and_teams(client, db):
    squads = "team,athlete,position\n" + "".join(
        f"{team},{team} {i},{'G' if i == 1 else ''}\n" for team in ("CPE", "MCE") for i in range(1, 8))
    t, admin = _tournament(client, db, "basketball", squads)
    client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(admin),
                content=fixtures_csv([("CPE", "MCE", "2026-11-12T16:40:00", "Court")]))
    client.post(f"/admin/tournaments/{t['id']}/publish", headers=auth(admin))
    match = client.get("/matches", params={"tournament_id": t["id"]}).json()[0]
    assert db.execute("select rules_version from matches where id = %s", (match["id"],)).fetchone()["rules_version"] \
        == "basketball-v2-draft"
    squad = client.get(f"/matches/{match['id']}").json()["squads"]
    ids = {a["name"]: a["id"] for side in squad.values() for a in side}
    assert {a["position"] for side in squad.values() for a in side} == {"G", "P"}

    fan = make_user(db, t["school_id"])
    picks = [f"CPE {i}" for i in range(1, 5)] + [f"MCE {i}" for i in range(1, 5)]    # no centres, no guards rule
    roles = {"CPE 1": "captain", "MCE 1": "vice_captain", "CPE 2": "key"}
    body = {"picks": [{"athlete_id": ids[p], "role": roles.get(p, "none")} for p in picks]}
    assert client.post(f"/matches/{match['id']}/teams", headers=auth(fan), json=body).status_code == 201
    six = [f"CPE {i}" for i in range(1, 7)] + ["MCE 1", "MCE 2"]                       # max 5 from one side
    body = {"picks": [{"athlete_id": ids[p], "role": roles.get(p, "none")} for p in six]}
    assert client.post(f"/matches/{match['id']}/teams", headers=auth(fan), json=body).status_code == 422
    rules = client.get("/sports/basketball/rules").json()
    assert [g["name"] for g in rules["positions"]] == ["players"]


# ---------- admin match-day reads ----------

def test_admin_match_list_and_scorer_picker(sw, client, db):
    tid, admin = sw["tournament"]["id"], sw["admin"]
    res = client.get(f"/admin/tournaments/{tid}/matches", headers=auth(admin)).json()
    first = next(m for m in res["matches"] if m["id"] == sw["match"]["id"])
    assert (first["scorers"], first["starters"], first["submissions"]) == (2, 22, 0)
    assert res["tournament"]["status"] == "published"
    scorers = client.get("/admin/users", params={"role": "scorer"}, headers=auth(admin)).json()
    assert {s["team_name"] for s in scorers} == {"scorer_one", "scorer_two"}
    other = make_user(db, make_school(db, "Elsewhere"), roles=("player", "admin"))
    assert client.get(f"/admin/tournaments/{tid}/matches", headers=auth(other)).status_code == 403
    assert client.get("/admin/users", headers=auth(sw["player"])).status_code == 403
