import sys
from tests.test_payments import FakePSPs, _player, _check, psp  # noqa: F401
from tests.conftest import auth


def test_recheck_credits_a_failed_fee_deposit(psp, client, db, db_url, monkeypatch):
    sys.path.insert(0, "scripts")
    import recheck_deposit as rd
    u = _player(db, client)
    d = client.post("/wallet/deposits", headers=auth(u), json={"amount_kobo": 100_000}).json()
    psp.txns[d["reference"]] = {"status": "success", "amount": 101_500}              # old behaviour: no requested_amount
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(u)).json()["status"] == "failed"
    psp.txns[d["reference"]]["requested_amount"] = 100_000
    monkeypatch.setattr(rd, "ENV", {"DATABASE_URL": db_url})
    monkeypatch.setattr(rd.getpass, "getpass", lambda _p: "sk_live_fake")
    monkeypatch.setattr("builtins.input", lambda _p: "YES")
    assert rd.main([d["reference"]]) == 0
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 100_000
    assert client.get(f"/wallet/deposits/{d['reference']}", headers=auth(u)).json()["status"] == "success"
    assert rd.main([d["reference"]]) == 0                                              # second run: nothing to do
    assert client.get("/me/wallet", headers=auth(u)).json()["cash_kobo"] == 100_000
    _check(db)
