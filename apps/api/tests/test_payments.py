"""Deposits and withdrawals against fake Paystack / Flutterwave servers (no network)."""
import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest

from app import payments, wallet
from app.config import settings
from tests.conftest import NOW, auth, make_school, make_user

PS_KEY, FLW_KEY, FLW_HASH = "sk_test_fake", "FLWSECK_TEST-fake", "flw-hash-fake"


class FakePSPs:
    """Just enough of both APIs. `paystack_up=False` simulates an outage."""

    def __init__(self):
        self.paystack_up = True
        self.txns = {}          # reference -> {"status", "amount" (kobo)}
        self.transfers = {}     # reference -> status
        self.account_name = "OBI ADA CHIOMA"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        body = json.loads(request.content) if request.content else {}
        if host == "api.paystack.co":
            if not self.paystack_up:
                return httpx.Response(503, json={"status": False, "message": "maintenance"})
            if path == "/transaction/initialize":
                self.txns[body["reference"]] = {"status": "pending", "amount": body["amount"]}
                return ok_ps({"authorization_url": f"https://checkout.paystack.com/{body['reference']}"})
            if path.startswith("/transaction/verify/"):
                t = self.txns[path.rsplit("/", 1)[1]]
                return ok_ps({"status": t["status"], "amount": t["amount"], "channel": "card", "fees": 150})
            if path == "/bank":
                return ok_ps([{"code": "058", "name": "GTBank"}, {"code": "044", "name": "Access Bank"}])
            if path == "/bank/resolve":
                return ok_ps({"account_name": self.account_name})
            if path == "/transferrecipient":
                return ok_ps({"recipient_code": "RCP_fake"})
            if path == "/transfer":
                self.transfers[body["reference"]] = "pending"
                return ok_ps({"status": "pending", "reference": body["reference"]})
            if path.startswith("/transfer/verify/"):
                return ok_ps({"status": self.transfers[path.rsplit("/", 1)[1]]})
        if host == "api.flutterwave.com":
            if path == "/v3/payments":
                self.txns[body["tx_ref"]] = {"status": "pending", "amount": int(body["amount"] * 100)}
                return ok_flw({"link": f"https://checkout.flutterwave.com/{body['tx_ref']}"})
            if path == "/v3/transactions/verify_by_reference":
                t = self.txns[request.url.params["tx_ref"]]
                return ok_flw({"status": {"success": "successful"}.get(t["status"], t["status"]),
                               "amount": t["amount"] / 100, "currency": "NGN", "payment_type": "card"})
        return httpx.Response(404, json={"status": False, "message": f"no fake for {host}{path}"})


def ok_ps(data):
    return httpx.Response(200, json={"status": True, "message": "ok", "data": data})


def ok_flw(data):
    return httpx.Response(200, json={"status": "success", "message": "ok", "data": data})


def ps_webhook(client, event: dict, key=PS_KEY):
    raw = json.dumps(event).encode()
    sig = hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
    return client.post("/payments/paystack/webhook", content=raw, headers={"x-paystack-signature": sig})


@pytest.fixture
def psp(monkeypatch):
    fake = FakePSPs()
    monkeypatch.setattr(payments, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(settings, "paystack_secret_key", PS_KEY)
    monkeypatch.setattr(settings, "flutterwave_secret_key", FLW_KEY)
    monkeypatch.setattr(settings, "flutterwave_webhook_hash", FLW_HASH)
    return fake


def _player(db, client, name="Ada Chioma Obi"):
    uid = make_user(db, make_school(db, f"School {name}"), team_name=name.split()[0].lower() + "_fc")
    assert client.post("/me/kyc", headers=auth(uid), json={
        "id_type": "nin", "number": f"1234567{abs(hash(name)) % 10000:04d}", "full_name": name}).json()["status"] \
        == "verified"
    return uid


def _check(db):
    c = wallet.ledger_check(db)
    assert c["balanced"] and c["negative_accounts"] == [], c


def test_deposit_is_credited_once_and_only_after_verify(psp, client, db):
    u = _player(db, client)
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 500_000}).json()
    assert d["provider"] == "paystack" and d["checkout_url"].endswith(d["reference"])
    event = {"event": "charge.success", "data": {"id": 991, "reference": d["reference"], "amount": 500_000}}

    assert ps_webhook(client, event, key="wrong").status_code == 401             # forged
    assert ps_webhook(client, event).json() == {"handled": True}
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 0      # provider still says pending

    psp.txns[d["reference"]]["status"] = "success"
    assert ps_webhook(client, {**event, "data": {**event["data"], "id": 992}}).json() == {"handled": True}
    assert ps_webhook(client, {**event, "data": {**event["data"], "id": 992}}).json() == {"handled": False}  # repeat
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(u)).json()["status"] == "success"
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 500_000
    _check(db)


def test_amount_mismatch_is_not_credited(psp, client, db):
    u = _player(db, client)
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 500_000}).json()
    psp.txns[d["reference"]] = {"status": "success", "amount": 100}                 # paid N1 for a N5,000 deposit
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(u)).json()["status"] == "failed"
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 0


def test_flutterwave_fallback_and_its_webhook(psp, client, db):
    u = _player(db, client)
    psp.paystack_up = False
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 250_000}).json()
    assert d["provider"] == "flutterwave"
    psp.txns[d["reference"]]["status"] = "success"
    raw = json.dumps({"event": "charge.completed", "data": {"id": 5, "tx_ref": d["reference"],
                                                            "status": "successful"}}).encode()
    assert client.post("/payments/flutterwave/webhook", content=raw, headers={"verif-hash": "nope"}).status_code == 401
    assert client.post("/payments/flutterwave/webhook", content=raw, headers={"verif-hash": FLW_HASH}).json()["handled"]
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 250_000


def test_deposit_rules(psp, client, db, monkeypatch):
    u = _player(db, client)
    assert client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 5_000}).json()["error"]["code"] \
        == "below_minimum"
    client.put("/me/limits", headers=auth(u), json={"daily_deposit_kobo": 1_000_000})
    client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 800_000})
    assert client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 300_000}).json()["error"]["code"] \
        == "deposit_limit"
    nokyc = make_user(db, make_school(db, "No KYC"), team_name="nokyc_fc")
    assert client.post("/wallet/deposits", headers=auth(nokyc), json={"amount_kobo": 500_000}).json()["error"][
        "code"] == "kyc_required"


def _fund(db, uid, kobo):
    with db.transaction():
        wallet.credit_deposit(db, uid, kobo, "paystack", None)


def test_withdrawals_approval_failure_reversal_and_success(psp, client, db):
    u = _player(db, client)
    school = db.execute("select school_id from users where id = %s", (u,)).fetchone()["school_id"]
    admin = make_user(db, school, roles=("player", "admin"), team_name="money_admin")
    _fund(db, u, 2_000_000)

    psp.account_name = "MUSA BELLO"
    assert client.post("/me/bank-accounts", headers=auth(u), json={"bank_code": "058", "account_number": "0123456789"}
                       ).json()["error"]["code"] == "name_mismatch"
    psp.account_name = "OBI ADA CHIOMA"
    acct = client.post("/me/bank-accounts", headers=auth(u), json={"bank_code": "058", "account_number": "0123456789"}
                       ).json()
    assert (acct["bank_name"], acct["last4"]) == ("GTBank", "6789")

    # First withdrawal waits for an admin; the money is held meanwhile.
    w = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 500_000, "bank_account_id": acct["id"]}
                    ).json()
    assert w["status"] == "awaiting_approval"
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 1_500_000
    assert [q["id"] for q in client.get("/admin/withdrawals", headers=auth(admin)).json()] == [w["id"]]
    assert client.post(f"/admin/withdrawals/{w['id']}/approve", headers=auth(admin)).json()["status"] == "pending"

    ref = db.execute("select psp_reference from withdrawals where id = %s", (w["id"],)).fetchone()["psp_reference"]
    psp.transfers[ref] = "failed"
    ps_webhook(client, {"event": "transfer.failed", "data": {"id": 7, "reference": ref}})
    assert db.execute("select status from withdrawals where id = %s", (w["id"],)).fetchone()["status"] == "reversed"
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 2_000_000      # money back

    # Rejected by the admin: also back.
    w2 = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 300_000,
                                                                   "bank_account_id": acct["id"]}).json()
    assert client.post(f"/admin/withdrawals/{w2['id']}/reject", headers=auth(admin)).json()["status"] == "rejected"
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 2_000_000

    # Approved and paid; the next small one goes straight out (no approval after a paid one).
    w3 = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 400_000,
                                                                   "bank_account_id": acct["id"]}).json()
    client.post(f"/admin/withdrawals/{w3['id']}/approve", headers=auth(admin))
    ref3 = db.execute("select psp_reference from withdrawals where id = %s", (w3["id"],)).fetchone()["psp_reference"]
    psp.transfers[ref3] = "success"
    ps_webhook(client, {"event": "transfer.success", "data": {"id": 8, "reference": ref3}})
    assert db.execute("select status from withdrawals where id = %s", (w3["id"],)).fetchone()["status"] == "paid"
    w4 = client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 100_000,
                                                                   "bank_account_id": acct["id"]}).json()
    assert w4["status"] == "pending" and not w4["needs_approval"]
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 1_500_000
    assert client.post("/wallet/withdrawals", headers=auth(u), json={"amount_kobo": 9_000_000,
                                                                     "bank_account_id": acct["id"]}
                       ).json()["error"]["code"] == "insufficient_funds"
    fin = client.get("/admin/finance", headers=auth(admin)).json()
    assert fin["ledger"]["balanced"] and fin["player_cash_kobo"] == 1_500_000
    _check(db)


def test_reconciliation_catches_a_missed_webhook(psp, client, db):
    from app.payments.service import reconcile
    u = _player(db, client)
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 300_000}).json()
    psp.txns[d["reference"]]["status"] = "success"
    with db.transaction():
        assert reconcile(db, NOW + timedelta(minutes=5)) == {"deposits": 0, "withdrawals": 0}   # too soon
        assert reconcile(db, NOW + timedelta(hours=1)) == {"deposits": 1, "withdrawals": 0}
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 300_000
