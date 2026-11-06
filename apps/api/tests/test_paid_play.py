"""Real money in the game: paid contests, H2H stakes, Home/Away result bets (Phase 5)."""
from datetime import timedelta

import pytest

from app import wallet
from app.config import settings
from app.settlement import refund_at_lock, release_payouts
from tests.conftest import auth, make_user, valid_picks
from tests.test_api_pilot import _finish, _team
from tests.test_api_scorer import ev, post, sw  # noqa: F401  (sw is a fixture)
from tests.test_api_teams import _variants

N = 100


@pytest.fixture(autouse=True)
def paid_on(monkeypatch):
    monkeypatch.setattr(settings, "paid_play_enabled", True)
    monkeypatch.setattr(settings, "result_bets_enabled", True)


def _player(db, sw, name, cash=10_000, coins=0):
    uid = make_user(db, sw["school"], team_name=name)
    db.execute("update users set kyc_status = 'verified' where id = %s", (uid,))
    with db.transaction():
        if cash:
            wallet.credit_deposit(db, uid, cash * N, "paystack", None)
        if coins:
            wallet.grant_bonus(db, uid, coins * N, "referral", sw["kickoff"])
    return uid


def _cash(db, uid):
    return wallet.balances(db, uid)["cash"] // N


def _check(db):
    c = wallet.ledger_check(db)
    assert c["balanced"] and c["negative_accounts"] == [], c


def _paid_contest(client, sw, fee_naira=1_000, capacity=5, name="Paid contest"):
    res = client.post(f"/admin/matches/{sw['match']['id']}/contests", headers=auth(sw["admin"]), json={
        "name": name, "capacity": capacity, "entry_fee_kobo": fee_naira * N})
    assert res.status_code == 201, res.json()
    return res.json()


def _goal_and_finish(client, sw, scorer_name="Engineering FWD 1"):
    mid, n = sw["match"]["id"], sw["names"]
    client.clock.now = sw["kickoff"] + timedelta(minutes=30)
    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, n[scorer_name], "goal", 29))
    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    _finish(client, sw, home=1, away=0)


def test_paid_contest_end_to_end_with_coins_and_24h_hold(sw, client, db):
    mid, names = sw["match"]["id"], sw["names"]
    v = _variants(names, 9)
    a = _player(db, sw, "alpha_fc", cash=500, coins=500)     # pays N500 coins + N500 cash
    b, c = _player(db, sw, "bravo_fc"), _player(db, sw, "charlie_fc")
    contest = _paid_contest(client, sw)
    assert contest["min_fill"] == 2
    for uid, picks in ((a, v[8]), (b, v[7]), (c, v[6])):      # captains: FWD 1, VC FWD 1, key FWD 1
        res = client.post(f"/contests/{contest['id']}/entries", headers=auth(uid),
                          json={"fantasy_team_id": _team(client, uid, mid, picks)})
        assert res.status_code == 201, res.json()
    assert wallet.balances(db, a) == {"cash": 0, "bonus": 0, "held_cash": 500 * N, "held_bonus": 500 * N}
    assert _cash(db, b) == 9_000

    _goal_and_finish(client, sw)
    # 3 x N1,000 = N3,000; 40% fee; the pool (N1,800) goes to 1st. Nothing paid until the hold ends.
    entries = {r["user_id"]: r for r in db.execute(
        "select user_id, final_rank, prize_kobo from contest_entries where contest_id = %s", (contest["id"],))}
    assert (entries[a]["final_rank"], entries[a]["prize_kobo"]) == (1, 1_800 * N)
    assert _cash(db, a) == 0
    with db.transaction():
        assert release_payouts(db, client.clock.now + timedelta(hours=23)) == {"contests": 0, "bets": 0}
        assert release_payouts(db, client.clock.now + timedelta(hours=25)) == {"contests": 1, "bets": 0}
        assert release_payouts(db, client.clock.now + timedelta(hours=26)) == {"contests": 0, "bets": 0}
    assert _cash(db, a) == 1_800                            # coins staked, winnings in cash
    assert (_cash(db, b), _cash(db, c)) == (9_000, 9_000)
    assert wallet.balance(db, wallet.PLATFORM_FEE) == 1_200 * N
    _check(db)


def test_leaving_refunds_and_underfilled_contests_refund_at_lock(sw, client, db):
    mid, names = sw["match"]["id"], sw["names"]
    a, b = _player(db, sw, "alpha_fc"), _player(db, sw, "bravo_fc")
    contest = _paid_contest(client, sw, capacity=20)          # needs 10 to run
    for uid in (a, b):
        client.post(f"/contests/{contest['id']}/entries", headers=auth(uid),
                    json={"fantasy_team_id": _team(client, uid, mid, valid_picks(names))})
    entry = db.execute("select id from contest_entries where user_id = %s", (b,)).fetchone()["id"]
    assert client.delete(f"/entries/{entry}", headers=auth(b)).status_code == 204
    assert _cash(db, b) == 10_000
    with db.transaction():
        assert refund_at_lock(db, sw["kickoff"] - timedelta(minutes=1)) == {"contests": 0, "bets": 0}
        assert refund_at_lock(db, sw["kickoff"] + timedelta(minutes=1)) == {"contests": 1, "bets": 0}
    assert _cash(db, a) == 10_000
    assert db.execute("select status from contests where id = %s", (contest["id"],)).fetchone()["status"] == "cancelled"
    _check(db)


def test_h2h_stake_winner_takes_both_less_commission(sw, client, db):
    mid, names = sw["match"]["id"], sw["names"]
    v = _variants(names, 9)
    a, b = _player(db, sw, "alpha_fc"), _player(db, sw, "bravo_fc")
    bet = client.post("/bets", headers=auth(a), json={"match_id": mid, "fantasy_team_id": _team(client, a, mid, v[8]),
                                                      "stake_kobo": 5_000 * N}).json()
    assert bet["status"] == "open" and _cash(db, a) == 5_000
    res = client.post(f"/bets/{bet['id']}/fills", headers=auth(b), json={"fantasy_team_id": _team(client, b, mid, v[0])})
    assert res.json()["status"] == "matched" and _cash(db, b) == 5_000
    _goal_and_finish(client, sw)
    with db.transaction():
        release_payouts(db, client.clock.now + timedelta(hours=25))
    assert (_cash(db, a), _cash(db, b)) == (5_000 + 9_500, 5_000)   # 10,000 - 10% of 5,000 profit
    mine = {x["id"]: x for x in client.get("/me/bets", headers=auth(a)).json()}[bet["id"]]
    assert (mine["result"], mine["payout_kobo"], mine["paid_out"]) == ("won", 9_500 * N, True)
    _check(db)


def test_unmatched_stake_is_refunded_at_lock(sw, client, db):
    mid, names = sw["match"]["id"], sw["names"]
    a = _player(db, sw, "alpha_fc")
    client.post("/bets", headers=auth(a), json={"match_id": mid, "fantasy_team_id": _team(client, a, mid, valid_picks(names)),
                                                "stake_kobo": 2_000 * N})
    with db.transaction():
        assert refund_at_lock(db, sw["kickoff"] + timedelta(minutes=1))["bets"] == 1
    assert _cash(db, a) == 10_000


@pytest.mark.parametrize("home_wins", [True, False])
def test_result_bet_with_three_challengers_matches_the_prd_example(sw, client, db, home_wins):
    """Stake N5,000 on Home; three challengers take N1,000 each on Away (PRD worked example)."""
    mid = sw["match"]["id"]
    creator = _player(db, sw, "home_backer")
    takers = [_player(db, sw, f"away_{i}_fc") for i in range(3)]
    bet = client.post("/bets", headers=auth(creator), json={"kind": "match_result", "match_id": mid, "side": "home",
                                                            "stake_kobo": 5_000 * N}).json()
    assert bet["status"] == "open"
    board = client.get(f"/matches/{mid}/bets").json()[0]
    assert (board["your_side"], board["win_up_to_kobo"]) == ("away", 9_500 * N)
    for i, t in enumerate(takers):
        res = client.post(f"/bets/{bet['id']}/fills", headers=auth(t), json={"amount_kobo": 1_000 * N}).json()
        assert res["status"] == "partially_matched" and res["quote"]["win"] == 1_900 * N
    assert client.post(f"/bets/{bet['id']}/fills", headers=auth(creator), json={"amount_kobo": 1_000 * N}).json()[
        "error"]["code"] == "cannot_accept"
    client.clock.now = sw["kickoff"] + timedelta(minutes=100)
    for s in (sw["s1"], sw["s2"]):
        post(client, s, mid, ev(1, sw["names"]["Engineering GK 1"], "save", 50))
    _finish(client, sw, home=1 if home_wins else 0, away=0 if home_wins else 1)
    with db.transaction():
        assert release_payouts(db, client.clock.now + timedelta(hours=25))["bets"] == 1
    if home_wins:
        assert _cash(db, creator) == 5_000 + 7_700 and [_cash(db, t) for t in takers] == [9_000] * 3
    else:
        assert _cash(db, creator) == 5_000 + 2_000 and [_cash(db, t) for t in takers] == [9_000 + 1_900] * 3
    _check(db)


def test_abandoned_match_refunds_everything_including_coins(sw, client, db):
    mid, names = sw["match"]["id"], sw["names"]
    a = _player(db, sw, "alpha_fc", cash=500, coins=500)
    b = _player(db, sw, "bravo_fc")
    contest = _paid_contest(client, sw)
    client.post(f"/contests/{contest['id']}/entries", headers=auth(a),
                json={"fantasy_team_id": _team(client, a, mid, valid_picks(names))})
    bet = client.post("/bets", headers=auth(b), json={"kind": "match_result", "match_id": mid, "side": "away",
                                                      "stake_kobo": 3_000 * N}).json()
    client.clock.now = sw["kickoff"] + timedelta(minutes=10)
    assert client.post(f"/admin/matches/{mid}/abandon", headers=auth(sw["admin"])).status_code == 200
    assert wallet.balances(db, a) == {"cash": 500 * N, "bonus": 500 * N, "held_cash": 0, "held_bonus": 0}
    assert _cash(db, b) == 10_000
    assert db.execute("select status from p2p_bets where id = %s", (bet["id"],)).fetchone()["status"] == "void"
    _check(db)


def test_who_may_not_play_for_money(sw, client, db, monkeypatch):
    mid, names = sw["match"]["id"], sw["names"]
    contest = _paid_contest(client, sw)
    # scorers can't stake on the match they score
    db.execute("update users set kyc_status = 'verified' where id = %s", (sw["s1"],))
    team = _team(client, sw["s1"], mid, valid_picks(names))
    assert client.post(f"/contests/{contest['id']}/entries", headers=auth(sw["s1"]),
                       json={"fantasy_team_id": team}).json()["error"]["code"] == "scorer_conflict"
    # unverified players
    team = _team(client, sw["player"], mid, valid_picks(names))
    assert client.post(f"/contests/{contest['id']}/entries", headers=auth(sw["player"]),
                       json={"fantasy_team_id": team}).json()["error"]["code"] == "kyc_required"
    # not enough money
    poor = _player(db, sw, "poor_fc", cash=100)
    assert client.post(f"/contests/{contest['id']}/entries", headers=auth(poor),
                       json={"fantasy_team_id": _team(client, poor, mid, valid_picks(names))}).json()["error"][
        "code"] == "insufficient_funds"
    # linked accounts (same bank account) can't bet against each other
    a, b = _player(db, sw, "alpha_fc"), _player(db, sw, "bravo_fc")
    for uid in (a, b):
        db.execute("""insert into bank_accounts (user_id, bank_code, bank_name, account_number, account_name)
                      values (%s, '058', 'GTBank', '0123456789', 'SAME PERSON')""", (uid,))
    bet = client.post("/bets", headers=auth(a), json={"kind": "match_result", "match_id": mid, "side": "home",
                                                      "stake_kobo": 2_000 * N}).json()
    assert "linked accounts" in client.post(f"/bets/{bet['id']}/fills", headers=auth(b),
                                            json={"amount_kobo": 1_000 * N}).json()["error"]["message"]
    # result bets have their own licence switch
    monkeypatch.setattr(settings, "result_bets_enabled", False)
    assert client.post("/bets", headers=auth(a), json={"kind": "match_result", "match_id": mid, "side": "home",
                                                       "stake_kobo": 2_000 * N}).json()["error"]["code"] \
        == "result_bets_unavailable"
    # fees are the N400 Mini or N1,000 and up
    assert client.post(f"/admin/matches/{mid}/contests", headers=auth(sw["admin"]), json={
        "name": "Odd", "capacity": 5, "entry_fee_kobo": 50_000}).json()["error"]["code"] == "bad_fee"
