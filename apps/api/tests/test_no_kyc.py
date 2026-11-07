"""KYC optional (the default for now), SportyBet-style: an 18+ tick box, a full name that bank accounts
must match, bank-transfer deposits, and withdrawals only back to an account that paid in."""
import uuid

import pytest

from app import wallet
from app.config import settings
from tests.conftest import NOW, auth, make_school, make_user
from tests.test_payments import psp  # noqa: F401  (fixture)

SENDER = {"sender_name": "OBI ADA CHIOMA", "sender_bank": "GTBank", "sender_bank_account_number": "XXXXXX6789"}


@pytest.fixture(autouse=True)
def no_kyc(client, monkeypatch):     # after `client`, which turns ID checks on for the older tests
    monkeypatch.setattr(settings, "kyc_required", False)
    monkeypatch.setattr(settings, "paid_play_enabled", True)


def _paid_in(client, psp, uid, amount=500_000, sender=SENDER):
    d = client.post("/wallet/deposits", headers=auth(uid), json={"amount_kobo": amount}).json()
    psp.txns[d["reference"]].update(status="success", channel="bank_transfer", authorization=sender)
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(uid)).json()["status"] == "success"
    return d


def test_tick_18_then_bank_transfer_deposit_records_who_paid(psp, client, db):
    u = make_user(db, make_school(db), team_name="chioma_fc")
    w = client.get("/me/wallet", headers=auth(u)).json()
    assert (w["kyc_required"], w["can_play_paid"], w["deposit_methods"]) == (False, False, ["bank_transfer"])
    assert client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 500_000}).json()["error"][
        "code"] == "confirm_18"
    assert client.post("/me/confirm-18", headers=auth(u), json={"confirm": False}).status_code == 422
    assert client.post("/me/confirm-18", headers=auth(u), json={"confirm": True}).json() == {"adult_confirmed": True}
    d = _paid_in(client, psp, u)
    assert psp.txns[d["reference"]]["channels"] == ["bank_transfer"]          # no cards until KYC
    row = db.execute("select payer_name, payer_bank, payer_account_tail from deposits where psp_reference = %s",
                     (d["reference"],)).fetchone()
    assert row == {"payer_name": "OBI ADA CHIOMA", "payer_bank": "GTBank", "payer_account_tail": "6789"}
    assert client.get("/me/wallet", headers=auth(u)).json()["can_play_paid"] is True


def test_withdrawals_only_back_to_the_account_that_paid_in_and_in_your_name(psp, client, db):
    school = make_school(db)
    u = make_user(db, school, team_name="chioma_fc")
    admin = make_user(db, school, roles=("player", "admin"), team_name="money_admin")
    client.post("/me/confirm-18", headers=auth(u), json={"confirm": True})
    add = lambda number: client.post("/me/bank-accounts", headers=auth(u),  # noqa: E731
                                     json={"bank_code": "058", "account_number": number}).json()
    assert add("0123456789")["error"]["code"] == "legal_name_required"        # no deposit, no bank name yet
    assert client.put("/me/legal-name", headers=auth(u), json={"legal_name": "Musa Bello"}).status_code in (404, 405)

    _paid_in(client, psp, u, 2_000_000)                       # the bank reports the payer: that's the name
    w = client.get("/me/wallet", headers=auth(u)).json()
    assert (w["legal_name"], w["legal_name_locked"]) == ("OBI ADA CHIOMA", True)
    _paid_in(client, psp, u, 100_000, {**SENDER, "sender_name": "MUSA BELLO"})   # later payers don't change it
    assert client.get("/me/wallet", headers=auth(u)).json()["legal_name"] == "OBI ADA CHIOMA"
    psp.account_name = "MUSA BELLO"
    assert add("0123456789")["error"]["code"] == "name_mismatch"               # someone else's account
    psp.account_name = "OBI ADA CHIOMA"
    assert add("0123450000")["error"]["code"] == "not_funding_account"         # never paid in from it
    acct = add("0123456789")
    assert acct["last4"] == "6789"

    w = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 500_000,
                                                                  "bank_account_id": acct["id"]}).json()
    assert w["status"] == "awaiting_approval"                                   # first one: an admin approves
    assert client.post(f"/admin/withdrawals/{w['id']}/approve", headers=auth(admin)).json()["status"] == "pending"
    ref = db.execute("select psp_reference from withdrawals where id = %s", (w["id"],)).fetchone()["psp_reference"]
    psp.transfers[ref] = "success"
    from tests.test_payments import ps_webhook
    ps_webhook(client, {"event": "transfer.success", "data": {"id": 81, "reference": ref}})
    w2 = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 100_000,
                                                                   "bank_account_id": acct["id"]}).json()
    assert w2["status"] == "pending" and not w2["needs_approval"]               # same bank: straight out


def test_bank_name_that_doesnt_line_up_goes_to_an_admin(psp, client, db):
    u = make_user(db, make_school(db), team_name="chioma_fc")
    client.post("/me/confirm-18", headers=auth(u), json={"confirm": True})
    _paid_in(client, psp, u, 2_000_000, {**SENDER, "sender_bank": "Guaranty Trust Bank"})
    acct = client.post("/me/bank-accounts", headers=auth(u), json={"bank_code": "058", "account_number": "0123456789"}
                       ).json()
    db.execute("""insert into withdrawals (user_id, amount_kobo, psp_reference, status, created_at, updated_at)
                  values (%s, 1, 'old', 'paid', %s, %s)""", (u, NOW, NOW))       # not a first withdrawal
    w = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 100_000,
                                                                  "bank_account_id": acct["id"]}).json()
    assert w["needs_approval"] is True                       # "GTBank" vs "Guaranty Trust Bank": a person checks


def test_referral_coins_only_from_a_bank_account_no_one_else_paid_in_from(psp, client, db):
    referrer = make_user(db, make_school(db), team_name="referrer")
    code = client.get("/me/referral", headers=auth(referrer)).json()["code"]
    school = db.execute("select school_id from users where id = %s", (referrer,)).fetchone()["school_id"]

    def friend(name):
        uid = uuid.uuid4()
        assert client.post("/me", headers=auth(uid), json={"school_id": str(school), "team_name": name,
                                                            "dob": "2003-05-01", "referral_code": code}).status_code == 201
        client.post("/me/confirm-18", headers=auth(uid), json={"confirm": True})
        return uid

    first, farmed = friend("first_friend"), friend("farmed_friend")
    _paid_in(client, psp, first, 100_000)
    assert client.get("/me/wallet", headers=auth(referrer)).json()["bonus_kobo"] == settings.referral_bonus_kobo
    _paid_in(client, psp, farmed, 100_000)                                      # same bank account as `first`
    assert client.get("/me/wallet", headers=auth(farmed)).json()["bonus_kobo"] == 0
    assert client.get("/me/wallet", headers=auth(referrer)).json()["bonus_kobo"] == settings.referral_bonus_kobo
    c = wallet.ledger_check(db)
    assert c["balanced"] and c["negative_accounts"] == []


def test_admin_sees_where_the_bank_name_came_from_and_can_correct_it(psp, client, db):
    school = make_school(db)
    u = make_user(db, school, team_name="chioma_fc")
    admin = make_user(db, school, roles=("player", "admin"), team_name="money_admin")
    other_admin = make_user(db, make_school(db, "Other Poly"), roles=("player", "admin"), team_name="far_admin")
    client.post("/me/confirm-18", headers=auth(u), json={"confirm": True})
    _paid_in(client, psp, u, 500_000, {**SENDER, "sender_name": "OBI MARY (MUM)"})    # paid from a parent's account
    view = client.get(f"/admin/users/{u}/bank-name", headers=auth(admin)).json()
    assert view["legal_name"] == "OBI MARY (MUM)" and view["deposits_from"][0]["payer_account_tail"] == "6789"
    assert client.get(f"/admin/users/{u}/bank-name", headers=auth(other_admin)).status_code == 403
    assert client.put(f"/admin/users/{u}/bank-name", headers=auth(admin), json={"legal_name": "Chioma"}).json()[
        "error"]["code"] == "bad_legal_name"
    fixed = client.put(f"/admin/users/{u}/bank-name", headers=auth(admin), json={"legal_name": " Obi  Ada Chioma "})
    assert fixed.json()["legal_name"] == "Obi Ada Chioma"
    assert client.get("/me/wallet", headers=auth(u)).json()["legal_name"] == "Obi Ada Chioma"
    assert client.put(f"/admin/users/{u}/bank-name", headers=auth(u), json={"legal_name": "Me Myself"}).status_code == 403
    audit = db.execute("select details from audit_log where action = 'user.correct_bank_name'").fetchone()["details"]
    assert audit["before"] == "OBI MARY (MUM)" and audit["after"] == "Obi Ada Chioma"


def test_no_payer_name_means_no_bank_name_until_an_admin_sets_it(psp, client, db):
    u = make_user(db, make_school(db), team_name="chioma_fc")
    client.post("/me/confirm-18", headers=auth(u), json={"confirm": True})
    _paid_in(client, psp, u, 500_000, {})                     # the provider didn't say who paid
    assert client.get("/me/wallet", headers=auth(u)).json()["legal_name"] is None
