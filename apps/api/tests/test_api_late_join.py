"""Late joining (agreed 6 Nov 2026): contests and new teams stay joinable until 67% of the match;
points recorded before joining are voided; late entries pay +50% and are paid by the same table."""
from datetime import timedelta

from app.matches import late_fee
from tests.conftest import auth, make_user, valid_picks
from tests.test_api_scorer import ev, post, sw  # noqa: F401  (sw is a fixture)
from tests.test_api_pilot import _finish, _free_contest, _team


def _board(client, contest_id, user=None):
    res = client.get(f"/contests/{contest_id}/leaderboard", headers=auth(user) if user else {}).json()
    return {e["team_name"]: e for e in res["entries"]}


def test_late_fee_is_150_percent():
    assert late_fee(100_000) == 150_000
    assert late_fee(40_000) == 60_000      # Mini ticket
    assert late_fee(0) == 0                # free contests stay free


def test_late_entry_only_counts_points_after_joining(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    early, late = sw["player"], make_user(db, sw["school"], team_name="late_fan")
    c = _free_contest(client, mid)
    t_early = _team(client, early, mid, valid_picks(n))       # captain Engineering FWD 1
    t_late = _team(client, late, mid, valid_picks(n))         # same picks, built before kick-off
    client.post(f"/contests/{c['id']}/entries", headers=auth(early), json={"fantasy_team_id": t_early})

    client.clock.now = sw["kickoff"] + timedelta(minutes=10)
    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 9))

    card = next(x for x in client.get(f"/matches/{mid}/contests", headers=auth(late)).json() if x["id"] == c["id"])
    assert card["locked"] and card["late_join"] == {"until_minute": 60, "minute": 10, "entry_fee_kobo": 0}
    joined = client.post(f"/contests/{c['id']}/entries", headers=auth(late), json={"fantasy_team_id": t_late})
    assert joined.status_code == 201 and joined.json()["late_elapsed_minutes"] == 10
    assert joined.json()["late_after_event_id"] is not None

    board = _board(client, c["id"])
    assert board["late_fan"]["points"] == 0                    # the minute-9 goal and +4 appearances are void
    assert board["late_fan"]["joined_minute"] == 10 and board["fan_one"]["joined_minute"] is None
    assert board["fan_one"]["points"] > 100

    client.clock.now = sw["kickoff"] + timedelta(minutes=40)
    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(2, n["Engineering FWD 1"], "goal", 38))
    board = _board(client, c["id"])
    # after joining: goal 40 x 2.5 (captain) = 100, and Law DEF 1 + Law DEF 2 conceded it (-2 each)
    assert board["late_fan"]["points"] == 96

    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw, home=2, away=0)
    final = _board(client, c["id"])
    # clean sheets are earned at the final whistle, after joining: Engineering GK 1, DEF 1, DEF 2 +20 each
    assert final["late_fan"]["points"] == 96 + 60 and final["late_fan"]["rank"] == 2
    assert final["fan_one"]["points"] > final["late_fan"]["points"]


def test_correcting_a_pre_join_event_does_not_touch_a_late_entry(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    late = make_user(db, sw["school"], team_name="late_fan")
    c = _free_contest(client, mid)
    t_late = _team(client, late, mid, valid_picks(n))
    client.clock.now = sw["kickoff"] + timedelta(minutes=10)
    post(client, sw["s1"], mid, ev(1, n["Engineering FWD 1"], "goal", 9))
    client.post(f"/contests/{c['id']}/entries", headers=auth(late), json={"fantasy_team_id": t_late})
    post(client, sw["s1"], mid, ev(2, n["Engineering FWD 1"], "goal", 9, reverses_client_seq=1))
    assert _board(client, c["id"])["late_fan"]["points"] == 0   # not -100 for an undo of a pre-join goal


def test_late_join_closes_at_67_percent(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    late = make_user(db, sw["school"], team_name="late_fan")
    c = _free_contest(client, mid)
    t_late = _team(client, late, mid, valid_picks(n))
    client.clock.now = sw["kickoff"] + timedelta(minutes=5)
    post(client, sw["s1"], mid, ev(1, n["Law GK 1"], "save", 61))   # the scorer says minute 61
    res = client.post(f"/contests/{c['id']}/entries", headers=auth(late), json={"fantasy_team_id": t_late})
    assert res.json()["error"]["code"] == "match_locked"            # recorded minute wins over the clock


def test_late_built_team_counts_from_creation_everywhere(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    late = make_user(db, sw["school"], team_name="late_fan")
    client.clock.now = sw["kickoff"] + timedelta(minutes=20)
    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 15))
    team = client.post(f"/matches/{mid}/teams", headers=auth(late), json={"picks": valid_picks(n)})
    assert team.status_code == 201
    tid = team.json()["id"]
    assert client.put(f"/teams/{tid}", headers=auth(late), json={"picks": valid_picks(n)}).json()["error"]["code"] \
        == "match_locked"                                             # late teams are frozen once saved
    bd = client.get(f"/teams/{tid}/breakdown", headers=auth(late)).json()
    assert bd["total_points"] == 0 and bd["joined_minute"] == 20
    fwd = next(p for p in bd["picks"] if p["display_name"] == "Engineering FWD 1")
    assert {"label": "Before you joined (20′)", "points": -44} in fwd["breakdown"]
    assert client.get(f"/matches/{mid}/summary", headers=auth(late)).json()["my_points"] == 0

    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw)
    season = client.get(f"/tournaments/{sw['tournament']['id']}/leaderboard").json()["entries"]
    # the minute-15 goal never counts; Engineering's clean sheet (GK 1, DEF 1, DEF 2) is earned at the end
    assert {e["team_name"]: e["points"] for e in season}["late_fan"] == 60
