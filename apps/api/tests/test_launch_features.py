"""Department pages, match previews and the notifications inbox."""
from datetime import timedelta

from app.imports import parse_squads
from app.notify import deadline_reminders
from tests.conftest import auth, make_user, valid_picks
from tests.test_api_pilot import _finish, _team
from tests.test_api_scorer import sw  # noqa: F401  (sw is a fixture)
from tests.test_api_teams import _variants


def test_squad_note_marks_the_captain():
    rows, _, errors = parse_squads("team,athlete,position,jersey,note\nCPE,Ada,GK,blue,captain\nCPE,Obi,DEF,,\n",
                                   "football")
    assert errors == [] and [(r[1], r[3]) for r in rows] == [("Ada", True), ("Obi", False)]


def test_department_page_and_match_preview(sw, client, db):
    mid = sw["match"]["id"]
    home_team = db.execute("select home_team_id from matches where id = %s", (mid,)).fetchone()["home_team_id"]
    db.execute("update athletes set is_captain = true where team_id = %s and display_name = 'Engineering FWD 1'",
               (home_team,))
    page = client.get(f"/teams/{home_team}/department").json()
    assert page["name"] == "Engineering" and len(page["sports"]) == 1
    football = page["sports"][0]
    assert football["captain"] == "Engineering FWD 1" and football["squad"][0]["is_captain"]
    assert football["next"]["id"] == mid and football["results"] == []
    assert football["table"]["played"] == 0

    before = client.get(f"/matches/{mid}/preview").json()
    assert before["home"]["captain"] == "Engineering FWD 1" and before["meetings"] == []

    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw, home=2, away=0)
    after = client.get(f"/teams/{home_team}/department").json()["sports"][0]
    assert after["results"][0]["outcome"] == "W" and after["results"][0]["score"] == {"for": 2, "against": 0}
    assert after["next"] is None and after["table"]["rank"] == 1
    p = client.get(f"/matches/{mid}/preview").json()
    assert (p["home"]["form"], p["away"]["form"]) == (["W"], ["L"])
    assert client.get("/teams/00000000-0000-0000-0000-000000000000/department").status_code == 404


def test_notifications_for_lineups_challenges_deadline_and_results(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    fan, rival = sw["player"], make_user(db, sw["school"], team_name="rival_fc")
    mine = _team(client, fan, mid, valid_picks(n))
    theirs = _team(client, rival, mid, _variants(n, 2)[1])

    starters = [a["id"] for side in ("home", "away")
                for a in client.get(f"/matches/{mid}").json()["squads"][side] if a["lineup"] == "starting"]
    assert client.post(f"/admin/matches/{mid}/lineup", headers=auth(sw["admin"]),
                       json={"starters": starters, "bench": []}).status_code == 200
    bet = client.post("/bets", headers=auth(fan), json={"match_id": mid, "fantasy_team_id": mine}).json()
    client.post(f"/bets/{bet['id']}/fills", headers=auth(rival), json={"fantasy_team_id": theirs})
    with db.transaction():
        first = deadline_reminders(db, sw["kickoff"] - timedelta(minutes=30))["sent"]
        deadline_reminders(db, sw["kickoff"] - timedelta(minutes=25))          # no repeats
    assert first >= 2
    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw, home=1, away=0)

    inbox = client.get("/me/notifications", headers=auth(fan)).json()
    kinds = [i["kind"] for i in inbox["items"]]
    assert sorted(kinds) == ["challenge_accepted", "deadline", "lineup", "result"] and inbox["unread"] == 4
    taken = next(i for i in inbox["items"] if i["kind"] == "challenge_accepted")
    assert taken["title"] == "rival_fc took on your challenge" and taken["link"] == "#/challenges"
    assert next(i for i in inbox["items"] if i["kind"] == "result")["title"] == "Full time: Engineering 1–0 Law"

    one = inbox["items"][0]["id"]
    assert client.post("/me/notifications/read", headers=auth(fan), json={"ids": [one]}).json()["unread"] == 3
    assert client.post("/me/notifications/read", headers=auth(fan), json={}).json()["unread"] == 0
    assert client.get("/me/notifications", headers=auth(rival)).json()["unread"] == 3   # no challenge note
