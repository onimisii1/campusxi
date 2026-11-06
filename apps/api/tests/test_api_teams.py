"""Fantasy team builder (PRD 5.3): rules, 10-team cap, duplicates, edits until lock."""
from datetime import datetime, timedelta

from tests.conftest import athletes_by_name, auth, valid_picks


def _url(world):
    return f"/matches/{world['match']['id']}/teams"


def test_create_valid_team(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    res = client.post(_url(world), headers=auth(world["player"]), json={"picks": valid_picks(names)})
    assert res.status_code == 201, res.json()
    team = res.json()
    assert team["label"] == "Team 1" and len(team["picks"]) == 11
    roles = {p["display_name"]: p["role"] for p in team["picks"]}
    assert roles["Engineering FWD 1"] == "captain" and roles["Law FWD 1"] == "vice_captain"


def test_invalid_team_lists_every_rule_broken(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    picks = valid_picks(names)
    picks[0] = {"athlete_id": names["Engineering DEF 3"], "role": "none"}      # no goalkeeper
    picks[-1]["role"] = "captain"                                               # two captains, no VC
    res = client.post(_url(world), headers=auth(world["player"]), json={"picks": picks})
    err = res.json()["error"]
    assert res.status_code == 422 and err["code"] == "invalid_team"
    assert "need at least 1 goalkeeper (got 0)" in err["details"]
    assert "choose exactly one Captain (got 2)" in err["details"]
    assert "choose exactly one Vice-captain (got 0)" in err["details"]


def test_athlete_from_another_match_rejected(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    picks = valid_picks(names)
    outsider = db.execute("select id from athletes where display_name = 'Medicine DEF 1'").fetchone()["id"]
    picks[1] = {"athlete_id": str(outsider), "role": "none"}
    err = client.post(_url(world), headers=auth(world["player"]), json={"picks": picks}).json()["error"]
    assert any("not in this match's squads" in d for d in err["details"])


def test_seven_per_side_cap(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    picks = valid_picks(names)
    picks[3] = {"athlete_id": names["Engineering DEF 3"], "role": "none"}  # 7 Engineering
    assert client.post(_url(world), headers=auth(world["player"]), json={"picks": picks}).status_code == 201
    picks[4] = {"athlete_id": names["Engineering DEF 4"], "role": "none"}  # 8 Engineering
    err = client.post(_url(world), headers=auth(world["player"]), json={"picks": picks}).json()["error"]
    assert any("at most 7 athletes from one side" in d for d in err["details"])


def test_duplicate_team_rejected(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    body = {"picks": valid_picks(names)}
    assert client.post(_url(world), headers=auth(world["player"]), json=body).status_code == 201
    res = client.post(_url(world), headers=auth(world["player"]), json=body)
    assert res.status_code == 409 and res.json()["error"]["code"] == "duplicate_team"


def _variants(names, n):
    """n distinct valid teams: rotate the captain across the outfield picks."""
    base = valid_picks(names)
    out = []
    for i in range(n):
        picks = [dict(p, role="none") for p in base]
        picks[1 + i % 10]["role"] = "captain"
        picks[1 + (i + 1) % 10]["role"] = "vice_captain"
        picks[1 + (i + 2) % 10]["role"] = "key"
        if i >= 10:
            picks[0] = {"athlete_id": names["Engineering GK 2"], "role": "none"}
        out.append(picks)
    return out


def test_ten_team_cap(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    teams = _variants(names, 11)
    for i, picks in enumerate(teams[:10], start=1):
        res = client.post(_url(world), headers=auth(world["player"]), json={"picks": picks})
        assert res.status_code == 201 and res.json()["label"] == f"Team {i}"
    res = client.post(_url(world), headers=auth(world["player"]), json={"picks": teams[10]})
    assert res.status_code == 409 and res.json()["error"]["code"] == "team_limit"
    assert len(client.get("/me/teams", headers=auth(world["player"]),
                          params={"match_id": world["match"]["id"]}).json()) == 10


def test_edit_until_lock_then_read_only(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    team = client.post(_url(world), headers=auth(world["player"]), json={"picks": valid_picks(names)}).json()
    picks = valid_picks(names)
    picks[0] = {"athlete_id": names["Law GK 1"], "role": "none"}
    res = client.put(f"/teams/{team['id']}", headers=auth(world["player"]), json={"picks": picks})
    assert res.status_code == 200
    assert "Law GK 1" in {p["display_name"] for p in res.json()["picks"]}

    client.clock.now = datetime.fromisoformat(world["match"]["scheduled_start"]) - timedelta(seconds=1)
    assert client.put(f"/teams/{team['id']}", headers=auth(world["player"]), json={"picks": picks}).status_code == 200

    client.clock.now += timedelta(seconds=1)
    res = client.put(f"/teams/{team['id']}", headers=auth(world["player"]), json={"picks": valid_picks(names)})
    assert res.status_code == 409 and res.json()["error"]["code"] == "match_locked"
    assert client.get(f"/matches/{world['match']['id']}").json()["locked"]

    # new teams may still be built late, until 67% of the 90 minutes (minute 60)
    client.clock.now += timedelta(minutes=59)
    late = client.post(_url(world), headers=auth(world["player"]), json={"picks": _variants(names, 3)[2]})
    assert late.status_code == 201 and late.json()["late_elapsed_minutes"] == 59
    client.clock.now += timedelta(minutes=1)
    res = client.post(_url(world), headers=auth(world["player"]), json={"picks": valid_picks(names)})
    assert res.json()["error"]["code"] == "match_locked"
    assert client.get(f"/matches/{world['match']['id']}").json()["late_join_until"] is None


def test_cannot_edit_someone_elses_team(world, client, db):
    from tests.conftest import make_user
    names = athletes_by_name(db, world["match"]["id"])
    team = client.post(_url(world), headers=auth(world["player"]), json={"picks": valid_picks(names)}).json()
    intruder = make_user(db, world["school"], team_name="intruder")
    res = client.put(f"/teams/{team['id']}", headers=auth(intruder), json={"picks": valid_picks(names)})
    assert res.status_code == 404


def test_edit_into_duplicate_of_own_other_team_rejected(world, client, db):
    names = athletes_by_name(db, world["match"]["id"])
    a, b = _variants(names, 2)
    client.post(_url(world), headers=auth(world["player"]), json={"picks": a})
    team_b = client.post(_url(world), headers=auth(world["player"]), json={"picks": b}).json()
    res = client.put(f"/teams/{team_b['id']}", headers=auth(world["player"]), json={"picks": a})
    assert res.json()["error"]["code"] == "duplicate_team"
    # saving team B unchanged is not a duplicate of itself
    assert client.put(f"/teams/{team_b['id']}", headers=auth(world["player"]), json={"picks": b}).status_code == 200
