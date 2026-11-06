"""Backend hardening: idempotency keys, rate limits, background jobs, health, attention list."""
from datetime import timedelta

import psycopg
import pytest

from app import jobs, wallet
from app.config import settings
from tests.conftest import NOW, auth, make_school, make_user
from tests.test_api_scorer import sw  # noqa: F401  (fixture)
from tests.test_payments import psp  # noqa: F401  (fixture)


def _verified(db, name="idem_fc"):
    uid = make_user(db, make_school(db, f"School {name}"), team_name=name)
    db.execute("update users set kyc_status = 'verified' where id = %s", (uid,))
    return uid


def test_retried_deposit_with_the_same_key_is_not_started_twice(psp, client, db):
    u = _verified(db)
    h = {**auth(u), "Idempotency-Key": "tap-123456789"}
    first = client.post("/wallet/deposits", headers=h, json={"amount_kobo": 200_000})
    again = client.post("/wallet/deposits", headers=h, json={"amount_kobo": 200_000})
    assert first.status_code == again.status_code == 201
    assert again.headers.get("Idempotent-Replay") == "true" and again.json() == first.json()
    assert db.execute("select count(*) as n from deposits").fetchone()["n"] == 1
    assert client.post("/wallet/withdrawals", headers=h, json={"amount_kobo": 60_000,
                                                               "bank_account_id": first.json()["id"]}
                       ).json()["error"]["code"] == "idempotency_key_reused"
    assert client.post("/wallet/deposits", headers={**auth(u), "Idempotency-Key": "short"},
                       json={"amount_kobo": 200_000}).status_code == 422


def test_rate_limit_on_id_checks(client, db, monkeypatch):
    import app.middleware as mw
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(mw.time, "monotonic", lambda: 1_000.0)   # no refills however slow the machine is
    u = make_user(db, make_school(db, "Rate"), team_name="rate_fc")
    codes = [client.post("/me/kyc", headers=auth(u), json={"id_type": "nin", "number": "11111110000",
                                                             "full_name": "Rate Test"}).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    # webhooks are never rate limited
    assert client.post("/payments/paystack/webhook", content=b"{}").status_code != 429


def test_jobs_run_once_and_skip_when_locked(client, db, db_url):
    u = _verified(db, "jobs_fc")
    with db.transaction():
        wallet.grant_bonus(db, u, 10_000, "referral", NOW)
    out = jobs.run_all(NOW + timedelta(days=91), db_url)
    assert out["expire_bonus"] == {"expired_kobo": 10_000}
    assert out["refund_at_lock"] == {"contests": 0, "bets": 0}
    assert out["reconcile_payments"]["skipped"] or out["reconcile_payments"] == {"deposits": 0, "withdrawals": 0}
    # another instance holding the job's lock makes this one skip
    with psycopg.connect(db_url, autocommit=False) as other:
        other.execute("select pg_advisory_xact_lock(hashtextextended('job:release_payouts', 0))")
        job = next(j for j in jobs.JOBS if j.name == "release_payouts")
        assert jobs.run_job(job, NOW, db_url) == {"skipped": "running elsewhere"}


def test_health_and_attention(sw, client, db):
    body = client.get("/health").json()
    assert body["database"] == "ok" and body["status"] == "ok" and "jobs" in body
    assert client.get("/health").headers.get("X-Request-ID")
    client.clock.now = sw["kickoff"] + timedelta(hours=4)
    stale = client.get("/admin/attention", headers=auth(sw["admin"])).json()
    assert [m["id"] for m in stale] == [sw["match"]["id"]]
