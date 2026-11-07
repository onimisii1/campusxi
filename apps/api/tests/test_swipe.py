"""Swipe to match: the open-challenge deck, skips, rewind and taking a card."""
from datetime import timedelta

import pytest

from app.config import settings
from tests.conftest import auth, make_user, valid_picks
from tests.test_api_pilot import _team
from tests.test_api_scorer import sw  # noqa: F401  (sw is a fixture)
from tests.test_api_teams import _variants


def _post(client, user, mid, team, **kw):
    res = client.post("/bets", headers=auth(user), json={"match_id": mid, "fantasy_team_id": team, **kw})
    assert res.status_code == 201, res.json()
    return res.json()


def _deck(client, user, **params):
    res = client.get("/bets/feed", headers=auth(user), params=params)
    assert res.status_code == 200, res.json()
    return res.json()


def test_deck_shows_other_peoples_open_challenges_until_skipped_or_taken(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    v = _variants(n, 4)
    rival, me = make_user(db, sw["school"], team_name="rival_fc"), make_user(db, sw["school"], team_name="swiper")
    a = _post(client, rival, mid, _team(client, rival, mid, v[1]))
    b = _post(client, rival, mid, _team(client, rival, mid, v[2]))
    _post(client, rival, mid, _team(client, rival, mid, v[3]), visibility="direct")   # links never show
    mine = _post(client, me, mid, _team(client, me, mid, valid_picks(n)))            # nor your own

    deck = _deck(client, me)
    assert {c["id"] for c in deck["cards"]} == {a["id"], b["id"]} and deck["skipped"] == 0
    card = deck["cards"][0]
    assert card["creator"]["team_name"] == "rival_fc" and card["match"]["home_team"]["name"] == "Engineering"
    assert [t["label"] for t in card["my_teams"]] == ["Team 1"] and "creator_fantasy_team_id" not in card
    assert len(_deck(client, me, match_id=mid)["cards"]) == 2
    assert _deck(client, me, sport="basketball")["cards"] == []

    assert client.post(f"/bets/{a['id']}/skip", headers=auth(me)).status_code == 204
    assert client.post(f"/bets/{a['id']}/skip", headers=auth(me)).status_code == 204   # twice is fine
    deck = _deck(client, me)
    assert [c["id"] for c in deck["cards"]] == [b["id"]] and deck["skipped"] == 1
    assert [c["id"] for c in _deck(client, rival)["cards"]] != []          # skips are per player
    assert client.delete(f"/bets/{a['id']}/skip", headers=auth(me)).status_code == 204   # rewind
    assert len(_deck(client, me)["cards"]) == 2
    client.post(f"/bets/{a['id']}/skip", headers=auth(me))
    client.post(f"/bets/{b['id']}/skip", headers=auth(me))
    assert _deck(client, me)["skipped"] == 2
    assert client.delete("/me/bet-skips", headers=auth(me)).status_code == 204
    assert len(_deck(client, me)["cards"]) == 2

    team = card["my_teams"][0]["id"]
    assert client.post(f"/bets/{a['id']}/fills", headers=auth(me), json={"fantasy_team_id": team}).json()[
        "status"] == "matched"
    assert [c["id"] for c in _deck(client, me)["cards"]] == [b["id"]]
    third = make_user(db, sw["school"], team_name="third_fc")
    assert {c["id"] for c in _deck(client, third)["cards"]} == {b["id"], mine["id"]}   # taken ones leave every deck

    client.clock.now = sw["kickoff"] + timedelta(minutes=1)
    assert _deck(client, me)["cards"] == []                                 # locked matches drop out
    assert client.post("/bets/00000000-0000-0000-0000-000000000000/skip", headers=auth(me)).status_code == 404


def test_staked_cards_only_for_players_who_could_take_them(sw, client, db, monkeypatch):
    from app import wallet
    monkeypatch.setattr(settings, "paid_play_enabled", True)
    mid, n = sw["match"]["id"], sw["names"]
    rich = make_user(db, sw["school"], team_name="staker")
    db.execute("update users set kyc_status = 'verified' where id = %s", (rich,))
    with db.transaction():
        wallet.credit_deposit(db, rich, 1_000_000, "paystack", None)
    staked = _post(client, rich, mid, _team(client, rich, mid, valid_picks(n)), stake_kobo=200_000)
    free = _post(client, rich, mid, _team(client, rich, mid, _variants(n, 2)[1]))
    unverified = make_user(db, sw["school"], team_name="no_id_yet")
    assert [c["id"] for c in _deck(client, unverified)["cards"]] == [free["id"]]
    verified = make_user(db, sw["school"], team_name="verified_fan")
    db.execute("update users set kyc_status = 'verified' where id = %s", (verified,))
    deck = _deck(client, verified)["cards"]
    assert {c["id"] for c in deck} == {staked["id"], free["id"]}
    assert next(c for c in deck if c["id"] == staked["id"])["win_up_to_kobo"] == 380_000


@pytest.mark.parametrize("path", ["/bets/feed"])
def test_deck_needs_sign_in(client, path):
    assert client.get(path).status_code == 401
