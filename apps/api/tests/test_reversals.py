"""Deposits the provider takes back after crediting (refunds, chargebacks)."""
import hashlib
import hmac
import json

from app import wallet
from app.config import settings
from tests.conftest import auth, make_school, make_user
from tests.test_payments import PS_KEY, psp  # noqa: F401  (fixture)


def _hook(client, event: dict):
    raw = json.dumps(event).encode()
    sig = hmac.new(PS_KEY.encode(), raw, hashlib.sha512).hexdigest()
    return client.post("/payments/paystack/webhook", content=raw, headers={"x-paystack-signature": sig})


def _setup(client, db, psp, amount=500_000):
    school = make_school(db)
    u = make_user(db, school, team_name="chioma_fc")
    admin = make_user(db, school, roles=("player", "admin"), team_name="money_admin")
    db.execute("update users set kyc_status = 'verified' where id = %s", (u,))
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": amount}).json()
    psp.txns[d["reference"]]["status"] = "success"
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(u)).json()["status"] == "success"
    return u, admin, d["reference"]


def _check(db):
    c = wallet.ledger_check(db)
    assert c["balanced"] and c["negative_accounts"] == [], c


def test_refund_is_verified_then_taken_back_from_the_wallet(psp, client, db):
    u, admin, ref = _setup(client, db, psp)
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 500_000
    _hook(client, {"event": "refund.processed", "data": {"id": 1, "transaction_reference": ref}})
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 500_000   # Paystack still says success
    psp.txns[ref]["status"] = "reversed"
    _hook(client, {"event": "refund.processed", "data": {"id": 2, "transaction_reference": ref}})
    w = client.get("/me/wallet", headers=auth(u)).json()
    assert w["cash_kobo"] == 0 and w["frozen_reason"] is None and w["can_play_paid"] is True
    row = db.execute("select status, shortfall_kobo from deposits where psp_reference = %s", (ref,)).fetchone()
    assert (row["status"], row["shortfall_kobo"]) == ("reversed", 0)
    _hook(client, {"event": "refund.processed", "data": {"id": 3, "transaction_reference": ref}})   # no double take
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 0
    kinds = {n["kind"] for n in client.get("/me/notifications", headers=auth(u)).json()["items"]}
    assert "deposit_reversed" in kinds
    assert any(n["kind"] == "admin_alert" for n in client.get("/me/notifications", headers=auth(admin)).json()["items"])
    _check(db)


def test_reversal_after_the_money_was_spent_books_a_loss_and_freezes_cash_play(psp, client, db, monkeypatch):
    monkeypatch.setattr(settings, "paid_play_enabled", True)
    u, admin, ref = _setup(client, db, psp)
    with db.transaction():
        wallet.hold(db, u, 300_000, "contest_entry", "00000000-0000-0000-0000-000000000001")   # ₦3,000 in play
    psp.txns[ref]["status"] = "reversed"
    _hook(client, {"event": "refund.processed", "data": {"id": 9, "transaction_reference": ref}})
    w = client.get("/me/wallet", headers=auth(u)).json()
    assert w["cash_kobo"] == 0 and w["frozen_reason"] and w["can_play_paid"] is False
    row = db.execute("select shortfall_kobo from deposits where psp_reference = %s", (ref,)).fetchone()
    assert row["shortfall_kobo"] == 300_000
    fin = client.get("/admin/finance", headers=auth(admin)).json()
    assert fin["reversal_loss_kobo"] == 300_000 and [f["team_name"] for f in fin["frozen"]] == ["chioma_fc"]
    assert client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 100_000}).json()["error"][
        "code"] == "money_frozen"
    assert client.post(f"/admin/users/{u}/unfreeze", headers=auth(admin)).json()["frozen"] is False
    assert client.get("/me/wallet", headers=auth(u)).json()["frozen_reason"] is None
    _check(db)


def test_chargeback_opened_freezes_without_moving_money(psp, client, db):
    u, admin, ref = _setup(client, db, psp)
    _hook(client, {"event": "charge.dispute.create", "data": {"id": 77, "transaction": {"reference": ref}}})
    w = client.get("/me/wallet", headers=auth(u)).json()
    assert w["cash_kobo"] == 500_000 and "chargeback" in w["frozen_reason"]
    alerts = [n for n in client.get("/me/notifications", headers=auth(admin)).json()["items"] if n["kind"] == "admin_alert"]
    assert alerts and alerts[0]["title"].startswith("Chargeback opened")
    _check(db)


def test_a_pending_deposit_reported_reversed_is_simply_failed(psp, client, db):
    u = make_user(db, make_school(db), team_name="late_fc")
    db.execute("update users set kyc_status = 'verified' where id = %s", (u,))
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 100_000}).json()
    psp.txns[d["reference"]]["status"] = "reversed"
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(u)).json()["status"] == "failed"
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 0
