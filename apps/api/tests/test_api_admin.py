"""Admin setup: tournaments, CSV import, line-ups, scorers, roles (PRD 5.2, 8.8)."""
from datetime import datetime, timedelta

from tests.conftest import auth, athletes_by_name, fixtures_csv, football_squads_csv, make_school, make_user


def _admin(db, school, team_name="admin_a"):
    return make_user(db, school, roles=("player", "admin"), team_name=team_name)


def test_players_cannot_use_admin_routes(client, db):
    school = make_school(db)
    player = make_user(db, school)
    res = client.post("/admin/tournaments", headers=auth(player), json={
        "school_id": str(school), "sport": "football", "name": "Cup", "match_minutes": 90})
    assert res.status_code == 403 and res.json()["error"]["code"] == "forbidden"


def test_admin_limited_to_own_school(client, db):
    mine, other = make_school(db, "Mine"), make_school(db, "Other")
    admin = _admin(db, mine)
    res = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(other), "sport": "football", "name": "Cup", "match_minutes": 90})
    assert res.json()["error"]["code"] == "other_school"


def test_coming_soon_sport_rejected(client, db):
    school = make_school(db)
    res = client.post("/admin/tournaments", headers=auth(_admin(db, school)), json={
        "school_id": str(school), "sport": "handball", "name": "Cup", "match_minutes": 60})
    assert res.json()["error"]["code"] == "sport_unavailable"


def test_full_setup_flow_and_lobby(world, client, db):
    m = world["match"]
    assert m["home_team"]["name"] == "Engineering" and m["away_team"]["name"] == "Law"
    assert m["sport"] == "football" and not m["locked"] and m["status"] == "scheduled"
    # naive "2026-11-12T16:00:00" is Lagos time -> 15:00 UTC; clock is 10 Nov 12:00 UTC
    assert m["seconds_to_lock"] == int(timedelta(days=2, hours=3).total_seconds())

    detail = client.get(f"/matches/{m['id']}").json()
    assert len(detail["squads"]["home"]) == 18 and len(detail["squads"]["away"]) == 18
    assert detail["scheduled_minutes"] == 90

    assert [s["code"] for s in client.get("/sports").json()][:3] == ["football", "basketball", "volleyball"]
    assert len(client.get("/tournaments").json()) == 1
    assert len(client.get("/matches", params={"sport": "basketball"}).json()) == 0

    actions = [r["action"] for r in db.execute("select action from audit_log order by id").fetchall()]
    assert actions == ["tournament.create", "tournament.import_squads", "tournament.import_fixtures",
                       "tournament.publish"]


def test_draft_tournaments_hidden_from_lobby(client, db):
    school = make_school(db)
    admin = _admin(db, school)
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": "football", "name": "Draft Cup", "match_minutes": 90}).json()
    client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin), content=football_squads_csv())
    client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(admin),
                content=fixtures_csv([("Engineering", "Law", "2026-11-12T16:00:00", "")]))
    assert client.get("/matches").json() == []
    assert len(client.get("/admin/tournaments", headers=auth(admin)).json()) == 1


def test_publish_needs_fixtures(client, db):
    school = make_school(db)
    admin = _admin(db, school)
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": "football", "name": "Empty", "match_minutes": 90}).json()
    assert client.post(f"/admin/tournaments/{t['id']}/publish", headers=auth(admin)).json()["error"]["code"] \
        == "no_fixtures"


def test_squad_csv_errors_are_all_or_nothing(world, client, db):
    t = world["tournament"]
    bad = "team,athlete,position\nEngineering,New Kid,WIZARD\nEngineering,,MID\nPhysics,A,MID\nPhysics,A,MID\n"
    res = client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(world["admin"]), content=bad)
    body = res.json()["error"]
    assert res.status_code == 422 and body["code"] == "invalid_csv"
    assert [d["row"] for d in body["details"]] == [2, 3, 5]
    assert "WIZARD" in body["details"][0]["message"]
    assert db.execute("select count(*) from teams where name = 'Physics'").fetchone()["count"] == 0


def test_team_sheet_codes_and_jersey_colours(client, db):
    """Real team sheets use LB/CB/CM/ST and a jersey colour (as on the NUESA squad posters)."""
    school = make_school(db)
    admin = _admin(db, school)
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": "football", "name": "Dept Cup", "match_minutes": 60}).json()
    sheet = ("team,athlete,position,jersey\n"
             "MCE,Keeper One,GK,white\nMCE,Left Back,LB,\nMCE,Centre Back,cb,\nMCE,Holding,DM,\n"
             "MCE,Playmaker,AM,\nMCE,Striker,ST,\n"
             "CPE,Their Keeper,Goalkeeper,Royal Blue\nCPE,Winger,RW,\n")
    res = client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin), content=sheet)
    assert res.status_code == 200, res.json()
    positions = {r["display_name"]: r["position"] for r in db.execute("select display_name, position from athletes")}
    assert positions == {"Keeper One": "GK", "Left Back": "DEF", "Centre Back": "DEF", "Holding": "MID",
                         "Playmaker": "MID", "Striker": "FWD", "Their Keeper": "GK", "Winger": "FWD"}
    client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(admin),
                content=fixtures_csv([("MCE", "CPE", "2026-11-12T16:00:00", "")]))
    client.post(f"/admin/tournaments/{t['id']}/publish", headers=auth(admin))
    m = client.get("/matches").json()[0]
    assert (m["home_team"]["colour"], m["away_team"]["colour"]) == ("#FAFAFA", "#1565C0")

    bad = "team,athlete,position,jersey\nMCE,A,GK,tartan\nMCE,B,CB,black\nEEE,C,CM,yellow\n"
    errs = client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin), content=bad).json()["error"]
    assert [d["row"] for d in errs["details"]] == [2]
    assert "tartan" in errs["details"][0]["message"]
    clash = "team,athlete,position,jersey\nEEE,A,GK,yellow\nEEE,B,CB,red\n"
    errs = client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin), content=clash).json()["error"]
    assert "two different jersey colours" in errs["details"][0]["message"]


def test_squad_reimport_updates_positions(world, client, db):
    t = world["tournament"]
    res = client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(world["admin"]),
                      content="team,athlete,position\nEngineering,Engineering MID 1,FWD\nEngineering,New Signing,DEF\n")
    assert res.json() == {"teams_created": 0, "athletes_created": 1, "athletes_updated": 1}
    pos = db.execute("select position from athletes where display_name = 'Engineering MID 1'").fetchone()
    assert pos["position"] == "FWD"


def test_fixture_csv_errors(world, client):
    t = world["tournament"]
    res = client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(world["admin"]), content=fixtures_csv([
        ("Engineering", "Physics", "2026-11-20T16:00:00", ""),
        ("Law", "Law", "2026-11-20T16:00:00", ""),
        ("Law", "Medicine", "next friday", ""),
    ]))
    rows = [d["row"] for d in res.json()["error"]["details"]]
    assert res.status_code == 422 and rows == [2, 3, 4]


def test_fixture_reimport_skips_existing(world, client):
    t = world["tournament"]
    res = client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(world["admin"]),
                      content=fixtures_csv([("Engineering", "Law", "2026-11-12T16:00:00", "Main Bowl")]))
    assert res.json() == {"matches_created": 0, "skipped_existing": 1}


def test_lineup_publish(world, client, db):
    m, admin = world["match"], world["admin"]
    names = athletes_by_name(db, m["id"])
    starters = [names[n] for n in names if n.endswith((" 1", " 2", " 3", " 4"))]
    # 4 per position per side would exceed 11 starters: Engineering has GK1-2, DEF1-4, MID1-4, FWD1-4 = 14
    res = client.post(f"/admin/matches/{m['id']}/lineup", headers=auth(admin), json={"starters": starters})
    assert res.json()["error"]["code"] == "too_many_starters"

    eng = [names[f"Engineering {p}"] for p in ("GK 1", "DEF 1", "DEF 2", "DEF 3", "DEF 4", "MID 1", "MID 2",
                                                "MID 3", "FWD 1", "FWD 2", "FWD 3")]
    res = client.post(f"/admin/matches/{m['id']}/lineup", headers=auth(admin),
                      json={"starters": eng, "bench": [names["Engineering GK 2"]]})
    assert res.status_code == 200 and res.json()["status"] == "lineup_out"
    detail = client.get(f"/matches/{m['id']}").json()
    lineup = {a["name"]: a["lineup"] for a in detail["squads"]["home"]}
    assert lineup["Engineering GK 1"] == "starting" and lineup["Engineering GK 2"] == "bench"
    assert lineup["Engineering MID 6"] is None and detail["lineup_out"]


def test_lineup_rejects_outsiders_and_locks(world, client, db):
    m, admin = world["match"], world["admin"]
    other = db.execute("select id from athletes where display_name = 'Medicine GK 1'").fetchone()["id"]
    res = client.post(f"/admin/matches/{m['id']}/lineup", headers=auth(admin), json={"starters": [str(other)]})
    assert res.json()["error"]["code"] == "unknown_athletes"

    client.clock.now = datetime.fromisoformat(m["scheduled_start"])
    names = athletes_by_name(db, m["id"])
    res = client.post(f"/admin/matches/{m['id']}/lineup", headers=auth(admin),
                      json={"starters": [names["Engineering GK 1"]]})
    assert res.status_code == 409 and res.json()["error"]["code"] == "match_locked"


def test_roles_and_scorers(world, client, db):
    m, admin, school = world["match"], world["admin"], world["school"]
    s1, s2 = make_user(db, school, team_name="scorer_1"), make_user(db, school, team_name="scorer_2")
    res = client.post(f"/admin/matches/{m['id']}/scorers", headers=auth(admin), json={"user_ids": [str(s1)]})
    assert res.json()["error"]["code"] == "not_scorers"

    for s in (s1, s2):
        res = client.post(f"/admin/users/{s}/roles", headers=auth(admin), json={"roles": ["scorer"]})
        assert res.json()["roles"] == ["player", "scorer"]
    res = client.post(f"/admin/matches/{m['id']}/scorers", headers=auth(admin), json={"user_ids": [str(s1), str(s2)]})
    assert res.status_code == 200
    assert db.execute("select count(*) from match_scorers").fetchone()["count"] == 2

    too_many = client.post(f"/admin/matches/{m['id']}/scorers", headers=auth(admin),
                           json={"user_ids": [str(s1), str(s2), str(admin)]})
    assert too_many.status_code == 422


def test_only_superadmin_grants_admin(world, client, db):
    target = make_user(db, world["school"], team_name="wannabe")
    res = client.post(f"/admin/users/{target}/roles", headers=auth(world["admin"]), json={"roles": ["admin"]})
    assert res.status_code == 403
    boss = make_user(db, world["school"], roles=("player", "superadmin"), team_name="boss")
    res = client.post(f"/admin/users/{target}/roles", headers=auth(boss), json={"roles": ["admin"]})
    assert res.json()["roles"] == ["admin", "player"]


def test_superadmin_creates_schools(client, db):
    school = make_school(db)
    boss = make_user(db, school, roles=("player", "superadmin"), team_name="boss")
    assert client.post("/admin/schools", headers=auth(boss), json={"name": "Second Poly"}).status_code == 201
    assert client.post("/admin/schools", headers=auth(boss), json={"name": "second poly"}).status_code == 409
    admin = _admin(db, school)
    assert client.post("/admin/schools", headers=auth(admin), json={"name": "Third"}).status_code == 403
    assert {s["name"] for s in client.get("/schools").json()} == {"Demo University", "Second Poly"}
