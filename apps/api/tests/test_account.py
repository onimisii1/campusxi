"""Account deletion (NDPA): erase personal details, keep money records anonymised."""
import httpx
import pytest

from app import wallet
from app.config import settings
from tests.conftest import NOW, auth, make_school, make_user
from tests.test_media import PNG


def _user(db, name="leaver_fc"):
    uid = make_user(db, make_school(db, f"School {name}"), team_name=name)
    db.execute("update users set kyc_status = 'verified' where id = %s", (uid,))
    return uid


def test_delete_needs_empty_wallet_then_erases_details(client, db):
    u = _user(db)
    with db.transaction():
        wallet.credit_deposit(db, u, 50_000, "paystack", None)
        wallet.grant_bonus(db, u, 20_000, "referral", NOW)
    assert client.delete("/me", headers=auth(u)).json()["error"]["code"] == "withdraw_first"

    with db.transaction():       # cash out (as a withdrawal would): held first...
        h = wallet.hold_withdrawal(db, u, 50_000, u, NOW)
    assert client.delete("/me", headers=auth(u)).json()["error"]["code"] == "money_in_play"
    with db.transaction():       # ...then paid
        wallet.complete_withdrawal(db, h, "paystack", NOW)
    client.put("/me/avatar", headers={**auth(u), "Content-Type": "image/png"}, content=PNG)

    res = client.delete("/me", headers=auth(u))
    assert res.status_code == 200, res.json()
    row = db.execute("select team_name, avatar_url, referral_code, deleted_at from users where id = %s", (u,)).fetchone()
    assert row["team_name"].startswith("deleted_") and row["avatar_url"] is None and row["deleted_at"] is not None
    assert db.execute("select count(*) as n from media where owner_id = %s", (u,)).fetchone()["n"] == 0
    assert wallet.balances(db, u)[wallet.BONUS] == 0                     # coins forfeited
    assert client.get("/me", headers=auth(u)).json()["error"]["code"] == "account_deleted"
    c = wallet.ledger_check(db)
    assert c["balanced"] and not c["negative_accounts"]


def test_money_in_play_blocks_deletion(client, db):
    u = _user(db, "inplay_fc")
    with db.transaction():
        wallet.credit_deposit(db, u, 100_000, "paystack", None)
        wallet.hold(db, u, 100_000, "contest_entry", u, now=NOW)
    assert client.delete("/me", headers=auth(u)).json()["error"]["code"] == "money_in_play"


def test_supabase_sign_in_is_removed_and_failures_roll_back(client, db, monkeypatch):
    u = _user(db, "supa_fc")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    assert client.delete("/me", headers=auth(u)).json()["error"]["code"] == "deletion_unavailable"

    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    calls = []
    def fake_delete(url, headers, timeout):
        calls.append((url, headers["apikey"]))
        return httpx.Response(500)
    monkeypatch.setattr(httpx, "delete", fake_delete)
    assert client.delete("/me", headers=auth(u)).json()["error"]["code"] == "deletion_failed"
    assert db.execute("select deleted_at from users where id = %s", (u,)).fetchone()["deleted_at"] is None  # rolled back

    monkeypatch.setattr(httpx, "delete", lambda url, headers, timeout: calls.append((url, headers["apikey"])) or httpx.Response(200))
    assert client.delete("/me", headers=auth(u)).json() == {"deleted": True}
    assert calls[-1] == (f"https://example.supabase.co/auth/v1/admin/users/{u}", "service-key")
