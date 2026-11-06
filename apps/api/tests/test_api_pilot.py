"""Free pilot (PRD Phase 4): free contests, leaderboards, free H2H challenges, season leaderboard."""
from datetime import timedelta

from tests.conftest import auth, make_user, valid_picks
from tests.test_api_scorer import ev, post, sw  # noqa: F401  (sw is a fixture)
from tests.test_api_teams import _variants


def _team(client, user, match_id, picks):
    res = client.post(f"/matches/{match_id}/teams", headers=auth(user), json={"picks": picks})
    assert res.status_code == 201, res.json()
    return res.json()["id"]


def _free_contest(client, match_id, user=None):
    contests = client.get(f"/matches/{match_id}/contests", headers=auth(user) if user else {}).json()
    return next(c for c in contests if c["name"] == "Free contest")


def _finish(client, sw, home=1, away=0):
    mid = sw["match"]["id"]
    for s in (sw["s1"], sw["s2"]):
        client.post(f"/scorer/matches/{mid}/submit", headers=auth(s), json={"home_score": home, "away_score": away})
    res = client.post(f"/admin/matches/{mid}/confirm", headers=auth(sw["admin"]),
                      json={"home_score": home, "away_score": away, "official_scorer_id": str(sw["s1"])})
    assert res.status_code == 200, res.json()


# ---------- contests ----------

def test_every_match_gets_a_free_contest(world, client, db):
    assert db.execute("select count(*) from contests where entry_fee_kobo = 0").fetchone()["count"] == 2
    c = _free_contest(client, world["match"]["id"])
    assert (c["capacity"], c["team_cap"], c["entries"], c["spots_left"]) == (1000, 10, 0, 1000)
    assert c["my_entries"] == [] and not c["locked"]


def test_join_rules(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    team = _team(client, sw["player"], mid, valid_picks(n))
    c = _free_contest(client, mid)
    url = f"/contests/{c['id']}/entries"
    assert client.post(url, headers=auth(sw["player"]), json={"fantasy_team_id": team}).status_code == 201
    again = client.post(url, headers=auth(sw["player"]), json={"fantasy_team_id": team})
    assert again.json()["error"]["code"] == "already_entered"
    other = make_user(db, sw["school"], team_name="other_fan")
    assert client.post(url, headers=auth(other), json={"fantasy_team_id": team}).json()["error"]["code"] \
        == "wrong_team"
    mine = _free_contest(client, mid, sw["player"])["my_entries"]
    assert [e["label"] for e in mine] == ["Team 1"]

    small = client.post(f"/admin/matches/{mid}/contests", headers=auth(sw["admin"]), json={
        "name": "Hall Cup", "capacity": 2, "team_cap": 1, "prize_text": "Jersey from the sports council"}).json()
    t2 = _team(client, sw["player"], mid, _variants(n, 2)[1])
    surl = f"/contests/{small['id']}/entries"
    assert client.post(surl, headers=auth(sw["player"]), json={"fantasy_team_id": team}).status_code == 201
    assert client.post(surl, headers=auth(sw["player"]), json={"fantasy_team_id": t2}).json()["error"]["code"] \
        == "team_cap"
    third = make_user(db, sw["school"], team_name="third_fan")
    t3 = _team(client, third, mid, valid_picks(n))
    assert client.post(surl, headers=auth(third), json={"fantasy_team_id": t3}).status_code == 201
    fourth = make_user(db, sw["school"], team_name="fourth_fan")
    t4 = _team(client, fourth, mid, valid_picks(n))
    assert client.post(surl, headers=auth(fourth), json={"fantasy_team_id": t4}).json()["error"]["code"] \
        == "contest_full"


def test_paid_contests_switched_off(sw, client):
    res = client.post(f"/admin/matches/{sw['match']['id']}/contests", headers=auth(sw["admin"]), json={
        "name": "Paid", "capacity": 100, "entry_fee_kobo": 100000})
    assert res.status_code == 403 and res.json()["error"]["code"] == "paid_play_unavailable"


def test_leave_until_lock(sw, client):
    mid, n = sw["match"]["id"], sw["names"]
    team = _team(client, sw["player"], mid, valid_picks(n))
    c = _free_contest(client, mid)
    entry = client.post(f"/contests/{c['id']}/entries", headers=auth(sw["player"]), json={"fantasy_team_id": team})
    assert client.delete(f"/entries/{entry.json()['id']}", headers=auth(sw["player"])).status_code == 204
    entry = client.post(f"/contests/{c['id']}/entries", headers=auth(sw["player"]), json={"fantasy_team_id": team})
    client.clock.now = sw["kickoff"]
    assert client.delete(f"/entries/{entry.json()['id']}", headers=auth(sw["player"])).status_code == 409
    late = client.post(f"/contests/{c['id']}/entries", headers=auth(sw["player"]), json={"fantasy_team_id": team})
    assert late.json()["error"]["code"] == "match_locked"


def test_live_then_final_leaderboard(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    rival = make_user(db, sw["school"], team_name="rival_fan")
    mine = _team(client, sw["player"], mid, valid_picks(n))               # captain Engineering FWD 1
    picks = valid_picks(n)
    for p in picks:
        p["role"] = {"Law FWD 1": "captain", "Engineering FWD 1": "vice_captain"}.get(
            next(k for k, v in n.items() if v == p["athlete_id"]), "none" if p["role"] != "key" else "key")
    theirs = _team(client, rival, mid, picks)
    c = _free_contest(client, mid)
    for user, team in ((sw["player"], mine), (rival, theirs)):
        client.post(f"/contests/{c['id']}/entries", headers=auth(user), json={"fantasy_team_id": team})

    board = client.get(f"/contests/{c['id']}/leaderboard", headers=auth(sw["player"])).json()
    assert board["source"] == "not_started" and {e["points"] for e in board["entries"]} == {0}

    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 10))
    board = client.get(f"/contests/{c['id']}/leaderboard", headers=auth(sw["player"])).json()
    assert board["source"] == "live"
    top = board["entries"][0]
    assert top["team_name"] == "fan_one" and top["rank"] == 1 and top["is_me"]
    assert board["entries"][1]["team_name"] == "rival_fan" and not board["entries"][1]["is_me"]

    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw)
    final = client.get(f"/contests/{c['id']}/leaderboard").json()
    assert final["status"] == "settled" and final["source"] == "final"
    assert [e["rank"] for e in final["entries"]] == [1, 2]
    stored = db.execute("select final_rank, final_points from contest_entries order by final_rank").fetchall()
    assert stored[0]["final_points"] > stored[1]["final_points"]


# ---------- free challenges ----------

def test_challenge_flow(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    rival = make_user(db, sw["school"], team_name="rival_fan")
    mine = _team(client, sw["player"], mid, valid_picks(n))
    theirs = _team(client, rival, mid, _variants(n, 3)[2])

    assert client.post("/bets", headers=auth(sw["player"]), json={
        "match_id": mid, "fantasy_team_id": mine, "stake_kobo": 100000}).json()["error"]["code"] \
        == "paid_play_unavailable"
    assert client.post("/bets", headers=auth(sw["player"]), json={
        "kind": "match_result", "match_id": mid, "fantasy_team_id": mine}).status_code == 403
    assert client.post("/bets", headers=auth(rival), json={"match_id": mid, "fantasy_team_id": mine}) \
        .json()["error"]["code"] == "wrong_team"

    bet = client.post("/bets", headers=auth(sw["player"]), json={"match_id": mid, "fantasy_team_id": mine}).json()
    assert bet["status"] == "open" and bet["invite_path"].startswith("#/challenge/")
    board = client.get(f"/matches/{mid}/bets", headers=auth(rival)).json()
    assert len(board) == 1 and board[0]["creator"] == {"team_name": "fan_one",
                                                        "record": {"won": 0, "lost": 0, "tied": 0}}
    assert "creator_fantasy_team_id" not in board[0] and not board[0]["is_mine"]

    token = bet["invite_path"].split("/")[-1]
    assert client.get(f"/bets/invite/{token}").json()["match"]["home_team"] == "Engineering"
    assert client.post(f"/bets/{bet['id']}/fills", headers=auth(sw["player"]),
                       json={"fantasy_team_id": mine}).json()["error"]["code"] == "cannot_accept"
    assert client.post(f"/bets/{bet['id']}/fills", headers=auth(rival),
                       json={"fantasy_team_id": theirs}).json()["status"] == "matched"
    third = make_user(db, sw["school"], team_name="late_fan")
    t3 = _team(client, third, mid, valid_picks(n))
    assert client.post(f"/bets/{bet['id']}/fills", headers=auth(third),
                       json={"fantasy_team_id": t3}).json()["error"]["code"] == "challenge_unavailable"
    assert client.get(f"/matches/{mid}/bets").json() == []

    unanswered = client.post("/bets", headers=auth(sw["player"]),
                             json={"match_id": mid, "fantasy_team_id": mine, "visibility": "direct"}).json()
    withdrawn = client.post("/bets", headers=auth(sw["player"]), json={"match_id": mid, "fantasy_team_id": mine}).json()
    assert client.post(f"/bets/{withdrawn['id']}/cancel", headers=auth(sw["player"])).json()["status"] == "cancelled"
    assert client.post(f"/bets/{bet['id']}/cancel", headers=auth(sw["player"])).json()["error"]["code"] \
        == "cannot_cancel"

    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 10))
    live = {b["id"]: b for b in client.get("/me/bets", headers=auth(sw["player"])).json()}
    assert live[bet["id"]]["my_points"] > live[bet["id"]]["opponent_points"]   # my captain scored
    assert live[bet["id"]]["opponent"] == "rival_fan"

    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw)
    mine_after = {b["id"]: b for b in client.get("/me/bets", headers=auth(sw["player"])).json()}
    assert mine_after[bet["id"]]["result"] == "won" and mine_after[bet["id"]]["status"] == "settled"
    assert mine_after[unanswered["id"]]["status"] == "cancelled"
    assert {b["id"]: b for b in client.get("/me/bets", headers=auth(rival)).json()}[bet["id"]]["result"] == "lost"
    events = db.execute("select to_status from p2p_bet_events where bet_id = %s order by id", (bet["id"],)).fetchall()
    assert [e["to_status"] for e in events] == ["open", "matched", "settled"]


def test_abandon_voids_contests_and_challenges(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    mine = _team(client, sw["player"], mid, valid_picks(n))
    client.post("/bets", headers=auth(sw["player"]), json={"match_id": mid, "fantasy_team_id": mine})
    client.post(f"/admin/matches/{mid}/abandon", headers=auth(sw["admin"]))
    assert {r["status"] for r in db.execute("select status from contests where match_id = %s", (mid,)).fetchall()} \
        == {"cancelled"}
    assert db.execute("select status from p2p_bets").fetchone()["status"] == "void"


# ---------- home card summary ----------

def test_match_summary(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    rival = make_user(db, sw["school"], team_name="rival_fan")
    _team(client, sw["player"], mid, valid_picks(n))                    # captain Engineering FWD 1
    _team(client, sw["player"], mid, _variants(n, 4)[3])
    _team(client, rival, mid, _variants(n, 4)[3])
    before = client.get(f"/matches/{mid}/summary", headers=auth(sw["player"])).json()
    assert (before["players"], before["teams"], before["my_teams"]) == (2, 3, 2)
    assert before["my_points"] is None and before["average"] is None and before["highest"] is None

    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 10))
    mine = client.get(f"/matches/{mid}/summary", headers=auth(sw["player"])).json()
    theirs = client.get(f"/matches/{mid}/summary", headers=auth(rival)).json()
    teams = client.get("/me/teams", headers=auth(sw["player"])).json()
    best = max(client.get(f"/teams/{t['id']}/breakdown", headers=auth(sw["player"])).json()["total_points"]
               for t in teams)
    assert mine["my_points"] == best == mine["highest"]
    assert float(mine["average"]) == round((float(best) + float(theirs["my_points"])) / 2, 1)
    assert client.get(f"/matches/{mid}/summary").json()["my_points"] is None   # signed out


# ---------- season leaderboard ----------

def test_season_leaderboard_counts_best_team_per_match(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    rival = make_user(db, sw["school"], team_name="rival_fan")
    _team(client, sw["player"], mid, valid_picks(n))                    # captain FWD 1 (scores)
    _team(client, sw["player"], mid, _variants(n, 4)[3])                # a weaker second team
    _team(client, rival, mid, _variants(n, 4)[3])
    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n["Engineering FWD 1"], "goal", 10))
    tid = sw["tournament"]["id"]
    assert client.get(f"/tournaments/{tid}/leaderboard").json()["entries"] == []   # nothing confirmed yet

    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw)
    board = client.get(f"/tournaments/{tid}/leaderboard", headers=auth(rival)).json()
    assert board["matches_confirmed"] == 1
    first, second = board["entries"]
    assert (first["team_name"], first["rank"], first["matches"]) == ("fan_one", 1, 1)
    assert second["team_name"] == "rival_fan" and second["is_me"] and first["points"] > second["points"]
    breakdown_best = max(
        client.get(f"/teams/{t['id']}/breakdown", headers=auth(sw["player"])).json()["total_points"]
        for t in client.get("/me/teams", headers=auth(sw["player"])).json())
    assert first["points"] == breakdown_best
