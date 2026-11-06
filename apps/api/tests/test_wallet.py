"""Wallet core (Phase 5): balanced ledger, holds, coins, ID checks, limits, referrals."""
from datetime import timedelta

import pytest

from app import wallet
from app.config import settings
from app.errors import ApiError
from tests.conftest import NOW, auth, make_school, make_user

N = 100   # kobo per naira


def _user(db, verified=True, **kw):
    school = make_school(db, f"School {kw.get('team_name', 'x')}")
    uid = make_user(db, school, **kw)
    if verified:
        db.execute("update users set kyc_status = 'verified' where id = %s", (uid,))
    return uid


def _fund(db, uid, naira):
    with db.transaction():
        wallet.credit_deposit(db, uid, naira * N, "paystack", None)


def _check(db):
    c = wallet.ledger_check(db)
    assert c["balanced"] and c["negative_accounts"] == [], c


def test_hold_takes_coins_first_up_to_half_and_releases_to_source(db):
    u = _user(db, team_name="coins_fan")
    _fund(db, u, 1_000)
    with db.transaction():
        wallet.grant_bonus(db, u, 800 * N, "referral", NOW)
        h = wallet.hold(db, u, 1_000 * N, "contest_entry", u)
    assert (h["bonus_kobo"], h["cash_kobo"]) == (500 * N, 500 * N)          # coins pay at most 50%
    assert wallet.balances(db, u) == {"cash": 500 * N, "bonus": 300 * N, "held_cash": 500 * N, "held_bonus": 500 * N}
    with db.transaction():
        wallet.release(db, h, NOW)
    assert wallet.balances(db, u) == {"cash": 1_000 * N, "bonus": 800 * N, "held_cash": 0, "held_bonus": 0}
    _check(db)


def test_insufficient_funds_and_withdrawals_never_use_coins(db):
    u = _user(db, team_name="short_fan")
    _fund(db, u, 300)
    with db.transaction():
        wallet.grant_bonus(db, u, 1_000 * N, "referral", NOW)
    with pytest.raises(ApiError) as e, db.transaction():
        wallet.hold(db, u, 1_000 * N, "contest_entry", u)                     # 500 coins + 500 cash > 300 cash
    assert e.value.code == "insufficient_funds" and e.value.details == {"short_kobo": 200 * N}
    with pytest.raises(ApiError), db.transaction():
        wallet.hold_withdrawal(db, u, 400 * N, u)                               # coins can't be withdrawn
    with db.transaction():
        h = wallet.hold_withdrawal(db, u, 300 * N, u)
    assert (h["cash_kobo"], h["bonus_kobo"]) == (300 * N, 0)
    _check(db)


def test_pot_pays_prizes_as_cash_even_when_staked_with_coins(db):
    a, b = _user(db, team_name="pot_a"), _user(db, team_name="pot_b")
    _fund(db, a, 500)
    _fund(db, b, 1_000)
    with db.transaction():
        wallet.grant_bonus(db, a, 500 * N, "referral", NOW)
        ha = wallet.hold(db, a, 1_000 * N, "contest_entry", a)                  # 500 coins + 500 cash
        hb = wallet.hold(db, b, 1_000 * N, "contest_entry", b)
        p = wallet.pot("contest", a)
        wallet.capture(db, ha, p, "entry_fee", NOW)
        wallet.capture(db, hb, p, "entry_fee", NOW)
        wallet.pay_out(db, p, {a: 1_200 * N}, 800 * N, "contest", a)           # a wins 1,200 cash; fee 800
    assert wallet.balances(db, a) == {"cash": 1_200 * N, "bonus": 0, "held_cash": 0, "held_bonus": 0}
    assert wallet.balance(db, wallet.PLATFORM_FEE) == 800 * N
    _check(db)


def test_refunded_coins_come_back_as_coins(db):
    a = _user(db, team_name="refund_a")
    _fund(db, a, 500)
    with db.transaction():
        wallet.grant_bonus(db, a, 500 * N, "referral", NOW)
        h = wallet.hold(db, a, 1_000 * N, "contest_entry", a)
        p = wallet.pot("contest", a)
        wallet.capture(db, h, p, "entry_fee", NOW)
        wallet.refund_pot(db, p, [h], NOW, "contest", a)
    assert wallet.balances(db, a)["bonus"] == 500 * N and wallet.balances(db, a)["cash"] == 500 * N
    _check(db)


def test_unbalanced_posts_are_refused(db):
    with pytest.raises(AssertionError), db.transaction():
        wallet.post(db, [("user:x:cash", 100, "deposit")])


def test_coins_expire_but_spent_or_held_coins_are_safe(db):
    u = _user(db, team_name="expiry_fan")
    with db.transaction():
        wallet.grant_bonus(db, u, 200 * N, "referral", NOW)
    with db.transaction():
        assert wallet.expire_bonus(db, NOW + timedelta(days=89)) == 0
        assert wallet.expire_bonus(db, NOW + timedelta(days=91)) == 200 * N
    assert wallet.balances(db, u)["bonus"] == 0
    _check(db)


# ---------- ID checks, limits, breaks, referrals (API) ----------

def test_kyc_stub_and_duplicate_identities(client, db):
    a, b = _user(db, verified=False, team_name="kyc_a"), _user(db, verified=False, team_name="kyc_b")
    body = {"id_type": "nin", "number": "12345678901", "full_name": "Ada Obi"}
    assert client.post("/me/kyc", headers=auth(a), json=body).json()["status"] == "verified"
    dup = client.post("/me/kyc", headers=auth(b), json=body).json()
    assert dup["status"] == "rejected" and "another account" in dup["reason"]
    assert client.post("/me/kyc", headers=auth(b), json={**body, "number": "12345670000"}).json()["status"] == "rejected"
    assert client.post("/me/kyc", headers=auth(b), json={**body, "number": "12345679999"}).json()["reason"] \
        == "the ID shows you're under 18"
    row = db.execute("select id_last4, identity_hash from kyc_records where user_id = %s", (a,)).fetchone()
    assert row["id_last4"] == "8901" and "12345678901" not in row["identity_hash"]
    assert client.get("/me/wallet", headers=auth(a)).json()["kyc_status"] == "verified"


def test_limits_lower_now_raise_after_24h_and_breaks(client, db, monkeypatch):
    from app.gate import require_paid_play
    monkeypatch.setattr(settings, "paid_play_enabled", True)
    u = _user(db, team_name="limits_fan")
    lim = client.put("/me/limits", headers=auth(u), json={"daily_stake_kobo": 2_000 * N}).json()
    assert lim["daily_stake_kobo"] == 2_000 * N
    client.clock.now = NOW + timedelta(hours=1)
    assert client.put("/me/limits", headers=auth(u), json={"daily_stake_kobo": 9_000 * N}).json()[
        "daily_stake_kobo"] == 2_000 * N                                       # raising waits 24h
    client.clock.now = NOW + timedelta(hours=26)
    assert client.get("/me/wallet", headers=auth(u)).json()["limits"]["daily_stake_kobo"] == 9_000 * N

    user = db.execute("select * from users where id = %s", (u,)).fetchone()
    require_paid_play(db, user, client.clock.now, 1_000 * N)                  # fine
    with pytest.raises(ApiError) as e:
        require_paid_play(db, user, client.clock.now, 10_000 * N)
    assert e.value.code == "stake_limit"
    client.post("/me/self-exclusion", headers=auth(u), json={"days": 7})
    with pytest.raises(ApiError) as e:
        require_paid_play(db, user, client.clock.now, 100 * N)
    assert e.value.code == "self_excluded"
    unverified = db.execute("select * from users where id = %s", (_user(db, verified=False, team_name="nokyc"),)).fetchone()
    with pytest.raises(ApiError) as e:
        require_paid_play(db, unverified, client.clock.now)
    assert e.value.code == "kyc_required"


def test_referral_coins_after_friend_verifies_and_deposits(client, db):
    referrer = _user(db, team_name="referrer")
    code = client.get("/me/referral", headers=auth(referrer)).json()["code"]
    school = db.execute("select school_id from users where id = %s", (referrer,)).fetchone()["school_id"]
    import uuid as _uuid
    friend = _uuid.uuid4()
    res = client.post("/me", headers=auth(friend), json={"school_id": str(school), "team_name": "new_friend",
                                                          "dob": "2003-05-01", "referral_code": code.lower()})
    assert res.status_code == 201 and res.json()["referred_by"] == str(referrer)
    client.post("/me/kyc", headers=auth(friend), json={"id_type": "bvn", "number": "22233344455", "full_name": "Femi Ade"}).raise_for_status()
    assert client.get("/me/wallet", headers=auth(referrer)).json()["bonus_kobo"] == 0     # no deposit yet

    from app.referrals import maybe_reward
    with db.transaction():
        d = db.execute("""insert into deposits (user_id, amount_kobo, psp, psp_reference, status, provider)
                          values (%s, 100000, 'paystack', 'ref-1', 'success', 'paystack') returning id""",
                       (friend,)).fetchone()
        wallet.credit_deposit(db, friend, 100_000, "paystack", d["id"])
        assert maybe_reward(db, friend, NOW) is True
        assert maybe_reward(db, friend, NOW) is False                          # only once
    assert client.get("/me/wallet", headers=auth(referrer)).json()["bonus_kobo"] == 200 * N
    assert client.get("/me/wallet", headers=auth(friend)).json()["bonus_kobo"] == 100 * N
    ref = client.get("/me/referral", headers=auth(referrer)).json()
    assert (ref["friends_rewarded"], ref["coins_earned_kobo"]) == (1, 200 * N)
    hist = client.get("/me/wallet/history", headers=auth(friend)).json()
    assert {h["label"] for h in hist} == {"Bonus coins", "Deposit"}
    _check(db)
