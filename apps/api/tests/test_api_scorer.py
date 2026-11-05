"""Scorer workflow (PRD 5.5, 5.6, 5.11): event batches, undo, live points, dual-scorer
reconciliation, confirmation, abandonment and postponement."""
from datetime import datetime, timedelta

import pytest

from tests.conftest import athletes_by_name, auth, make_user, valid_picks

ENG_XI = ["GK 1", "DEF 1", "DEF 2", "DEF 3", "DEF 4", "MID 1", "MID 2", "MID 3", "MID 4", "FWD 1", "FWD 2"]


@pytest.fixture
def sw(world, client, db):
    """`world` plus two assigned scorers, a published line-up, and the clock 20 minutes before kick-off."""
    m, admin, school = world["match"], world["admin"], world["school"]
    names = athletes_by_name(db, m["id"])
    s1 = make_user(db, school, roles=("player", "scorer"), team_name="scorer_one")
    s2 = make_user(db, school, roles=("player", "scorer"), team_name="scorer_two")
    assert client.post(f"/admin/matches/{m['id']}/scorers", headers=auth(admin),
                       json={"user_ids": [str(s1), str(s2)]}).status_code == 200
    starters = [names[f"Engineering {p}"] for p in ENG_XI] + [names[f"Law {p}"] for p in ENG_XI]
    assert client.post(f"/admin/matches/{m['id']}/lineup", headers=auth(admin),
                       json={"starters": starters, "bench": [names["Engineering FWD 3"]]}).status_code == 200
    kickoff = datetime.fromisoformat(m["scheduled_start"])
    client.clock.now = kickoff - timedelta(minutes=20)
    return {**world, "names": names, "s1": s1, "s2": s2, "kickoff": kickoff}


def ev(seq, athlete, etype, minute=None, **kw):
    return {"client_seq": seq, "athlete_id": athlete, "event_type": etype, "minute": minute, **kw}


def post(client, scorer, match_id, *events):
    return client.post(f"/scorer/matches/{match_id}/events", headers=auth(scorer), json={"events": list(events)})


def statuses(res):
    return [r["status"] for r in res.json()["results"]]


def live(client, match_id):
    return {a["name"]: a["points"] for a in client.get(f"/matches/{match_id}/live").json()["athletes"]}


# ---------- access and timing ----------

def test_only_assigned_scorers(sw, client, db):
    mid = sw["match"]["id"]
    other = make_user(db, sw["school"], roles=("player", "scorer"), team_name="not_assigned")
    assert post(client, other, mid, ev(1, sw["names"]["Engineering GK 1"], "save")).json()["error"]["code"] \
        == "not_assigned"
    assert post(client, sw["player"], mid, ev(1, sw["names"]["Engineering GK 1"], "save")).status_code == 403
    mine = client.get("/scorer/matches", headers=auth(sw["s1"])).json()
    assert [(x["id"], x["role"]) for x in mine] == [(mid, "primary")]


def test_scoring_opens_30_minutes_before_kickoff(sw, client):
    client.clock.now = sw["kickoff"] - timedelta(minutes=31)
    res = post(client, sw["s1"], sw["match"]["id"], ev(1, sw["names"]["Engineering GK 1"], "save"))
    assert res.json()["error"]["code"] == "too_early"


def test_lineup_must_be_published(world, client, db):
    m = world["match"]
    s = make_user(db, world["school"], roles=("player", "scorer"), team_name="lonely_scorer")
    client.post(f"/admin/matches/{m['id']}/scorers", headers=auth(world["admin"]), json={"user_ids": [str(s)]})
    client.clock.now = datetime.fromisoformat(m["scheduled_start"])
    names = athletes_by_name(db, m["id"])
    assert post(client, s, m["id"], ev(1, names["Engineering GK 1"], "save")).json()["error"]["code"] \
        == "lineup_missing"


# ---------- event batches ----------

def test_first_event_makes_match_live_and_locks_teams(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    team = client.post(f"/matches/{mid}/teams", headers=auth(sw["player"]), json={"picks": valid_picks(n)})
    assert team.status_code == 201
    res = post(client, sw["s1"], mid, ev(1, n["Engineering FWD 1"], "goal", 3))
    assert statuses(res) == ["accepted"] and res.json()["last_client_seq"] == 1
    assert client.get(f"/matches/{mid}").json()["status"] == "live"
    edit = client.put(f"/teams/{team.json()['id']}", headers=auth(sw["player"]), json={"picks": valid_picks(n)})
    assert edit.json()["error"]["code"] == "match_locked"


def test_resend_is_duplicate_and_reused_seq_rejected(sw, client):
    mid, n = sw["match"]["id"], sw["names"]
    first = ev(1, n["Engineering FWD 1"], "goal", 10)
    assert statuses(post(client, sw["s1"], mid, first)) == ["accepted"]
    assert statuses(post(client, sw["s1"], mid, first, ev(2, n["Law GK 1"], "save", 12))) \
        == ["duplicate", "accepted"]
    res = post(client, sw["s1"], mid, ev(2, n["Law GK 1"], "save", 13))
    assert statuses(res) == ["rejected"] and "different event" in res.json()["results"][0]["error"]


def test_invalid_events_rejected_individually(sw, client):
    mid, n = sw["match"]["id"], sw["names"]
    res = post(client, sw["s1"], mid,
               ev(1, n["Engineering FWD 1"], "shot_on_target", 5),     # dropped from v1 scoring
               ev(2, n["Engineering MID 6"], "assist", 6),             # not in the line-up
               ev(3, n["Engineering FWD 1"], "goal"),                  # football goal needs a minute
               ev(4, n["Engineering FWD 1"], "goal", 7, amount=2),     # only basketball points take amounts
               ev(5, n["Engineering FWD 1"], "goal", 8))
    assert statuses(res) == ["rejected"] * 4 + ["accepted"]
    errors = [r.get("error", "") for r in res.json()["results"]]
    assert "not an event in football" in errors[0] and "line-up" in errors[1]
    assert "minute" in errors[2] and "amount" in errors[3]


def test_undo_rules(sw, client):
    mid, n = sw["match"]["id"], sw["names"]
    fwd = n["Engineering FWD 1"]
    post(client, sw["s1"], mid, ev(1, fwd, "goal", 10), ev(2, n["Engineering MID 1"], "assist", 10))
    assert live(client, mid)["Engineering FWD 1"] == 44
    res = post(client, sw["s1"], mid,
               ev(3, fwd, "goal", 10, reverses_client_seq=1),
               ev(4, fwd, "goal", 10, reverses_client_seq=1),                       # already undone
               ev(5, fwd, "goal", 10, reverses_client_seq=3),                       # undo of an undo
               ev(6, fwd, "assist", 10, reverses_client_seq=2),                     # wrong athlete for #2
               ev(7, fwd, "goal", 10, reverses_client_seq=99))                      # nothing there
    assert statuses(res) == ["accepted", "rejected", "rejected", "rejected", "rejected"]
    assert live(client, mid)["Engineering FWD 1"] == 4
    detail = client.get(f"/scorer/matches/{mid}", headers=auth(sw["s1"])).json()
    assert detail["last_client_seq"] == 3 and detail["events"][2]["reverses_client_seq"] == 1


# ---------- live points ----------

def test_live_points_follow_primary_and_team_breakdown(sw, client):
    mid, n = sw["match"]["id"], sw["names"]
    team = client.post(f"/matches/{mid}/teams", headers=auth(sw["player"]), json={"picks": valid_picks(n)}).json()
    post(client, sw["s1"], mid, ev(1, n["Engineering FWD 1"], "goal", 10), ev(2, n["Engineering MID 1"], "assist", 10))
    post(client, sw["s2"], mid, ev(1, n["Engineering FWD 2"], "goal", 10))   # secondary disagrees
    body = client.get(f"/matches/{mid}/live").json()
    assert body["source"] == "primary_scorer"
    pts = {a["name"]: a for a in body["athletes"]}
    assert pts["Engineering FWD 1"]["points"] == 44 and pts["Engineering FWD 2"]["points"] == 4
    assert pts["Law GK 1"]["points"] == 2           # started, conceded one
    assert pts["Engineering FWD 1"]["breakdown"] == [{"label": "In starting line-up", "points": 4},
                                                     {"label": "Goal (FWD)", "points": 40}]
    assert body["athletes"][0]["name"] == "Engineering FWD 1"   # sorted by points

    bd = client.get(f"/teams/{team['id']}/breakdown", headers=auth(sw["player"])).json()
    by = {p["display_name"]: p for p in bd["picks"]}
    assert by["Engineering FWD 1"]["points"] == 110            # captain x2.5
    assert by["Engineering MID 1"]["points"] == 36             # key x1.5 on 4 + 20
    assert by["Law FWD 1"]["points"] == 8                      # vice-captain x2 on 4
    assert by["Law DEF 1"]["points"] == 2                      # 4 - 2 conceded
    assert bd["total_points"] == sum(p["points"] for p in bd["picks"])


# ---------- submission, reconciliation, confirmation ----------

def _agreeing_streams(client, sw):
    mid, n = sw["match"]["id"], sw["names"]
    for s in (sw["s1"], sw["s2"]):
        res = post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 10),
                   ev(2, n["Engineering MID 1"], "assist", 10), ev(3, n["Law DEF 1"], "yellow", 30))
        assert statuses(res) == ["accepted"] * 3


def test_submit_flow_and_reconcile_agreement(sw, client):
    mid = sw["match"]["id"]
    _agreeing_streams(client, sw)
    res = client.post(f"/scorer/matches/{mid}/submit", headers=auth(sw["s1"]), json={"home_score": 1, "away_score": 0})
    assert res.json() == {"match_id": mid, "status": "live", "waiting_for_scorers": 1}
    late = post(client, sw["s1"], mid, ev(4, sw["names"]["Law GK 1"], "save", 80))
    assert late.json()["error"]["code"] == "already_submitted"
    res = client.post(f"/scorer/matches/{mid}/submit", headers=auth(sw["s2"]), json={"home_score": 1, "away_score": 0})
    assert res.json()["status"] == "final_pending"
    rec = client.get(f"/admin/matches/{mid}/reconcile", headers=auth(sw["admin"])).json()
    assert rec["agreed"] and rec["event_mismatches"] == [] and rec["points_differences"] == []


def test_reconcile_flags_disagreement_then_reopen_and_fix(sw, client):
    mid, n = sw["match"]["id"], sw["names"]
    post(client, sw["s1"], mid, ev(1, n["Engineering FWD 1"], "goal", 10))
    post(client, sw["s2"], mid, ev(1, n["Engineering FWD 2"], "goal", 10))
    for s in (sw["s1"], sw["s2"]):
        client.post(f"/scorer/matches/{mid}/submit", headers=auth(s), json={"home_score": 1, "away_score": 0})
    rec = client.get(f"/admin/matches/{mid}/reconcile", headers=auth(sw["admin"])).json()
    assert not rec["agreed"]
    assert {(x["athlete"], x["primary"], x["secondary"]) for x in rec["event_mismatches"]} == {
        ("Engineering FWD 1", 1, 0), ("Engineering FWD 2", 0, 1)}
    assert {x["athlete"] for x in rec["points_differences"]} == {"Engineering FWD 1", "Engineering FWD 2"}

    res = client.post(f"/admin/matches/{mid}/reopen", headers=auth(sw["admin"]), json={"scorer_id": str(sw["s2"])})
    assert res.json()["status"] == "live"
    fix = post(client, sw["s2"], mid, ev(2, n["Engineering FWD 2"], "goal", 10, reverses_client_seq=1),
               ev(3, n["Engineering FWD 1"], "goal", 10))
    assert statuses(fix) == ["accepted", "accepted"]
    client.post(f"/scorer/matches/{mid}/submit", headers=auth(sw["s2"]), json={"home_score": 1, "away_score": 0})
    assert client.get(f"/admin/matches/{mid}/reconcile", headers=auth(sw["admin"])).json()["agreed"]


def test_confirm_result(sw, client, db):
    mid = sw["match"]["id"]
    _agreeing_streams(client, sw)
    early = client.post(f"/admin/matches/{mid}/confirm", headers=auth(sw["admin"]),
                        json={"home_score": 1, "away_score": 0, "official_scorer_id": str(sw["s1"])})
    assert early.json()["error"]["code"] == "not_ready"
    for s in (sw["s1"], sw["s2"]):
        client.post(f"/scorer/matches/{mid}/submit", headers=auth(s), json={"home_score": 1, "away_score": 0})

    stranger = make_user(db, sw["school"], roles=("player", "scorer"), team_name="stranger")
    bad = client.post(f"/admin/matches/{mid}/confirm", headers=auth(sw["admin"]),
                      json={"home_score": 1, "away_score": 0, "official_scorer_id": str(stranger)})
    assert bad.json()["error"]["code"] == "not_official_scorer"
    shootout = client.post(f"/admin/matches/{mid}/confirm", headers=auth(sw["admin"]),
                           json={"home_score": 1, "away_score": 0, "shootout_winner": "home",
                                 "official_scorer_id": str(sw["s2"])})
    assert shootout.json()["error"]["code"] == "shootout_needs_draw"

    client.clock.now = sw["kickoff"] + timedelta(minutes=110)
    res = client.post(f"/admin/matches/{mid}/confirm", headers=auth(sw["admin"]),
                      json={"home_score": 1, "away_score": 0, "official_scorer_id": str(sw["s2"])}).json()
    assert res["winner"] == "home" and res["status"] == "confirmed"
    assert datetime.fromisoformat(res["payout_after"]) == client.clock.now + timedelta(hours=24)

    body = client.get(f"/matches/{mid}/live").json()
    assert body["source"] == "official" and body["result"]["winner"] == "home"
    assert {a["name"]: a["points"] for a in body["athletes"]}["Law DEF 1"] == 4 - 4 - 2
    closed = post(client, sw["s1"], mid, ev(9, sw["names"]["Law GK 1"], "save", 85))
    assert closed.json()["error"]["code"] == "not_scoring"
    actions = [r["action"] for r in db.execute("select action from audit_log order by id").fetchall()]
    assert actions[-1] == "match.confirm"


def test_drawn_football_with_shootout(sw, client):
    mid = sw["match"]["id"]
    for s in (sw["s1"], sw["s2"]):
        client.post(f"/scorer/matches/{mid}/submit", headers=auth(s),
                    json={"home_score": 0, "away_score": 0, "shootout_winner": "away"})
    res = client.post(f"/admin/matches/{mid}/confirm", headers=auth(sw["admin"]),
                      json={"home_score": 0, "away_score": 0, "shootout_winner": "away",
                            "official_scorer_id": str(sw["s1"])}).json()
    assert res["winner"] == "draw" and res["shootout_winner"] == "away"


def test_scorers_fixed_once_scoring_starts(sw, client):
    mid = sw["match"]["id"]
    post(client, sw["s1"], mid, ev(1, sw["names"]["Law GK 1"], "save", 2))
    res = client.post(f"/admin/matches/{mid}/scorers", headers=auth(sw["admin"]), json={"user_ids": [str(sw["s2"])]})
    assert res.json()["error"]["code"] == "scoring_started"


# ---------- abandon and postpone ----------

def test_abandon(sw, client):
    mid = sw["match"]["id"]
    post(client, sw["s1"], mid, ev(1, sw["names"]["Law GK 1"], "save", 2))
    assert client.post(f"/admin/matches/{mid}/abandon", headers=auth(sw["admin"])).json()["status"] == "abandoned"
    assert post(client, sw["s1"], mid, ev(2, sw["names"]["Law GK 1"], "save", 3)).json()["error"]["code"] \
        == "not_scoring"
    assert client.post(f"/admin/matches/{mid}/abandon", headers=auth(sw["admin"])).status_code == 409


def test_postpone_with_and_without_new_date(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    held = client.post(f"/admin/matches/{mid}/postpone", headers=auth(sw["admin"]), json={}).json()
    assert held["status"] == "postponed"
    locked = client.post(f"/matches/{mid}/teams", headers=auth(sw["player"]), json={"picks": valid_picks(n)})
    assert locked.json()["error"]["code"] == "match_locked"

    new_start = (sw["kickoff"] + timedelta(days=7)).isoformat()
    res = client.post(f"/admin/matches/{mid}/postpone", headers=auth(sw["admin"]), json={"new_start": new_start})
    assert res.json()["status"] == "scheduled"
    row = db.execute("select scheduled_start, original_start from matches where id = %s", (mid,)).fetchone()
    assert row["original_start"] == sw["kickoff"] and row["scheduled_start"] == sw["kickoff"] + timedelta(days=7)
    client.clock.now = sw["kickoff"] + timedelta(hours=1)    # past the old start, before the new one
    assert client.post(f"/matches/{mid}/teams", headers=auth(sw["player"]),
                       json={"picks": valid_picks(n)}).status_code == 201


def test_live_match_cannot_be_postponed(sw, client):
    mid = sw["match"]["id"]
    post(client, sw["s1"], mid, ev(1, sw["names"]["Law GK 1"], "save", 2))
    res = client.post(f"/admin/matches/{mid}/postpone", headers=auth(sw["admin"]), json={})
    assert res.json()["error"]["code"] == "cannot_postpone"
