"""Tournament views checked against the NUESA 2026/27 Matchday 1 posters (Thu 5 Nov 2026)."""
from decimal import Decimal

from tests.conftest import auth, make_school, make_user

DEPTS = ("CPE", "MEE", "MCE", "EEE", "PGE", "CVE")
FOOTBALL_SQUADS = {"CPE": ["Alvin Zika", "Nikkis"], "MEE": ["Nacizio Anthonio"], "MCE": ["Nyong"],
                   "CVE": ["Valentine"], "EEE": ["Ewoma"], "PGE": ["Kolo"]}
BASKETBALL_SQUADS = {"MCE": ["Okoro", "Tomini", "Jordan"], "CPE": ["Chris"], "CVE": ["Pauly Ivote"],
                     "MEE": ["Fred"], "EEE": ["Charbel"], "PGE": ["Owoyomi Paul"]}


def _setup(client, db, sport, squads, results, stats=None):
    school = make_school(db, f"Nile University {sport}")
    admin = make_user(db, school, roles=("player", "admin"))
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": sport, "name": "NUESA Sports Tournament 2026/27",
        "match_minutes": 30}).json()
    pos = "MID" if sport == "football" else ""
    csv = "team,athlete,position\n" + "".join(f"{team},{a},{pos}\n" for team, names in squads.items() for a in names)
    assert client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin), content=csv).status_code == 200
    res = client.post(f"/admin/tournaments/{t['id']}/results", headers=auth(admin), content=results)
    assert res.status_code == 200, res.text
    if stats:
        res = client.post(f"/admin/tournaments/{t['id']}/result-stats", headers=auth(admin), content=stats)
        assert res.status_code == 200, res.text
    client.post(f"/admin/tournaments/{t['id']}/fixtures", headers=auth(admin), content=(
        "home_team,away_team,scheduled_start,venue,code\nCPE,PGE,2026-11-06T16:00:00,Pitch,X4\n"))
    assert client.post(f"/admin/tournaments/{t['id']}/publish", headers=auth(admin)).status_code == 200
    return t, admin


FOOTBALL_RESULTS = ("code,home_team,away_team,home_score,away_score,played_at\n"
                    "M1,MEE,MCE,1,1,2026-11-05T16:00:00\nM3,CPE,CVE,2,1,2026-11-05T17:20:00\n")
FOOTBALL_STATS = ("code,team,athlete,goals,assists\nM1,MEE,Nacizio Anthonio,1,\nM1,MCE,Nyong,1,0\n"
                  "M3,CPE,Alvin Zika,1,\nM3,CPE,Nikkis,1,\nM3,CVE,Valentine,1,\n")


def test_football_table_and_golden_boot_match_the_posters(client, db):
    t, _ = _setup(client, db, "football", FOOTBALL_SQUADS, FOOTBALL_RESULTS, FOOTBALL_STATS)
    rows = client.get(f"/tournaments/{t['id']}/standings").json()["rows"]
    table = [(r["rank"], r["shared"], r["team"]["name"], r["played"], r["won"], r["drawn"], r["lost"],
              r["for"], r["against"], r["difference"], r["points"]) for r in rows]
    assert table == [
        (1, False, "CPE", 1, 1, 0, 0, 2, 1, 1, 3),
        (2, True, "MCE", 1, 0, 1, 0, 1, 1, 0, 1),
        (2, True, "MEE", 1, 0, 1, 0, 1, 1, 0, 1),
        (4, True, "EEE", 0, 0, 0, 0, 0, 0, 0, 0),
        (4, True, "PGE", 0, 0, 0, 0, 0, 0, 0, 0),
        (6, False, "CVE", 1, 0, 0, 1, 1, 2, -1, 0),
    ]
    assert rows[0]["form"] == ["W"]

    boot = client.get(f"/tournaments/{t['id']}/stats").json()
    assert boot["kind"] == "golden_boot"
    assert {(p["rank"], p["name"], p["matches"], p["assists"], p["goals"]) for p in boot["players"]} == {
        (1, n, 1, 0, 1) for n in ("Alvin Zika", "Nacizio Anthonio", "Nikkis", "Nyong", "Valentine")}

    # Imported results have no fantasy play, and the match card shows the final score.
    assert client.get(f"/tournaments/{t['id']}/leaderboard").json()["entries"] == []
    cards = {m["code"]: m for m in client.get("/matches", params={"tournament_id": t["id"]}).json()}
    assert cards["M3"]["score"] == {"home": 2, "away": 1, "walkover": False, "final": True}
    assert cards["X4"]["score"] is None and cards["X4"]["stage"] == "league"
    live = client.get(f"/matches/{cards['M3']['id']}/live").json()
    assert {a["name"] for a in live["athletes"]} == {"Alvin Zika", "Nikkis", "Valentine"}


def test_golden_boot_tiebreaks(client, db):
    results = FOOTBALL_RESULTS + "M5,MEE,CVE,0,0,2026-11-06T16:40:00\n"
    stats = ("code,team,athlete,goals,assists\nM1,MEE,Nacizio Anthonio,1,\nM3,CPE,Alvin Zika,1,1\n"
             "M3,CPE,Nikkis,1,\nM5,MEE,Nacizio Anthonio,0,0\n")
    t, _ = _setup(client, db, "football", FOOTBALL_SQUADS, results, stats)
    players = client.get(f"/tournaments/{t['id']}/stats").json()["players"]
    # level on goals: more assists first, then fewer matches played
    assert [(p["name"], p["rank"]) for p in players] == [("Alvin Zika", 1), ("Nikkis", 2), ("Nacizio Anthonio", 3)]


def test_basketball_table_and_mvp_match_the_posters(client, db):
    results = ("code,home_team,away_team,home_score,away_score,played_at\n"
               "G1,MEE,MCE,28,40,2026-11-05T16:00:00\nG2,CPE,CVE,24,18,2026-11-05T16:40:00\n"
               "G3,EEE,PGE,27,22,2026-11-05T17:20:00\n")
    stats = ("code,team,athlete,pts,reb,ast,stl,blk\nG1,MCE,Okoro,4,9,4,3,4\nG1,MCE,Tomini,20,3,2,2,0\n"
             "G2,CPE,Chris,9,11,1,2,0\nG1,MCE,Jordan,12,1,2,4,0\nG2,CVE,Pauly Ivote,7,8,1,3,0\n")
    t, _ = _setup(client, db, "basketball", BASKETBALL_SQUADS, results, stats)
    rows = client.get(f"/tournaments/{t['id']}/standings").json()["rows"]
    assert [(r["team"]["name"], r["won"], r["lost"], r["for"], r["against"], r["difference"], r["points"])
            for r in rows] == [("MCE", 1, 0, 40, 28, 12, 2), ("CPE", 1, 0, 24, 18, 6, 2), ("EEE", 1, 0, 27, 22, 5, 2),
                               ("PGE", 0, 1, 22, 27, -5, 0), ("CVE", 0, 1, 18, 24, -6, 0),
                               ("MEE", 0, 1, 28, 40, -12, 0)]
    mvp = client.get(f"/tournaments/{t['id']}/stats").json()
    assert mvp["kind"] == "mvp"
    assert [(p["rank"], p["name"], Decimal(str(p["total"])), Decimal(str(p["average"]))) for p in mvp["players"]] == [
        (1, "Okoro", Decimal("36.3"), Decimal("36.3")), (2, "Tomini", Decimal("31.6"), Decimal("31.6")),
        (3, "Chris", Decimal("28.7"), Decimal("28.7")), (4, "Jordan", Decimal("26.2"), Decimal("26.2")),
        (5, "Pauly Ivote", Decimal("25.6"), Decimal("25.6"))]
    assert mvp["players"][0]["rebounds"] == 9 and mvp["players"][0]["matches"] == 1


def test_bad_imports_are_rejected_whole(client, db):
    school = make_school(db, "Nile bad imports")
    admin = make_user(db, school, roles=("player", "admin"))
    t = client.post("/admin/tournaments", headers=auth(admin), json={
        "school_id": str(school), "sport": "basketball", "name": "NUESA", "match_minutes": 32}).json()
    client.post(f"/admin/tournaments/{t['id']}/squads", headers=auth(admin),
                content="team,athlete,position\nCPE,Chris,\nMCE,Okoro,\n")
    url = f"/admin/tournaments/{t['id']}/results"
    bad = ("code,home_team,away_team,home_score,away_score,played_at\n"
           "G1,CPE,MCE,24,18,2026-11-05T16:00:00\nG2,CPE,MCE,20,20,2026-11-05T17:00:00\n"
           "G3,CPE,ZZZ,1,0,yesterday\n")
    err = client.post(url, headers=auth(admin), content=bad).json()["error"]
    assert err["code"] == "invalid_csv" and sorted({d["row"] for d in err["details"]}) == [3, 4]
    assert db.execute("select count(*) as n from matches where tournament_id = %s", (t["id"],)).fetchone()["n"] == 0

    client.post(url, headers=auth(admin), content="code,home_team,away_team,home_score,away_score,played_at\n"
                                                  "G1,CPE,MCE,24,18,2026-11-05T16:00:00\n")
    stats = "code,team,athlete,pts,reb,ast,stl,blk\nG1,CPE,Chris,9,11,1,2,0\nG1,MCE,Nobody,1,0,0,0,0\nG9,CPE,Chris,1,,,,\n"
    err = client.post(f"/admin/tournaments/{t['id']}/result-stats", headers=auth(admin), content=stats).json()["error"]
    assert [d["row"] for d in err["details"]] == [3, 4]
    assert db.execute("select count(*) as n from stat_events").fetchone()["n"] == 0


def test_bracket_placeholders_then_knockouts(client, db):
    t, admin = _setup(client, db, "football", FOOTBALL_SQUADS, FOOTBALL_RESULTS)
    b = client.get(f"/tournaments/{t['id']}/bracket").json()
    assert [(s["home"], s["away"], s["projected"]) for s in b["semis"]] == [
        ("1st in table", "4th in table", ["CPE", "EEE"]), ("2nd in table", "3rd in table", ["MCE", "MEE"])]
    assert (b["final"]["home"], b["final"]["away"]) == ("Winner SF1", "Winner SF2")

    teams = {r["name"]: str(r["id"]) for r in client.get(f"/tournaments/{t['id']}").json()["teams"]}
    for code, home, away in (("SF1", "CPE", "PGE"), ("SF2", "MEE", "MCE")):
        res = client.post(f"/admin/tournaments/{t['id']}/knockout", headers=auth(admin), json={
            "stage": "semi", "home_team_id": teams[home], "away_team_id": teams[away],
            "scheduled_start": "2026-12-01T16:00:00+01:00", "code": code})
        assert res.status_code == 201, res.text
    dup = client.post(f"/admin/tournaments/{t['id']}/knockout", headers=auth(admin), json={
        "stage": "final", "home_team_id": teams["CPE"], "away_team_id": teams["MEE"],
        "scheduled_start": "2026-12-05T16:00:00+01:00", "code": "sf1"})
    assert dup.json()["error"]["code"] == "code_taken"
    b = client.get(f"/tournaments/{t['id']}/bracket").json()
    assert [(s["code"], s["home"], s["away"], s["placeholder"]) for s in b["semis"]] == [
        ("SF1", "CPE", "PGE", False), ("SF2", "MEE", "MCE", False)]
    assert (b["final"]["home"], b["final"]["away"], b["final"]["placeholder"]) == ("Winner SF1", "Winner SF2", True)
    # knockout matches stay out of the league table
    assert sum(r["played"] for r in client.get(f"/tournaments/{t['id']}/standings").json()["rows"]) == 4
