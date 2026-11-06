"""Deposits, withdrawals, bank accounts, provider webhooks, and the admin withdrawal queue."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.audit import audit
from app.auth import Identity, current_identity, current_user, require_admin
from app.clock import utcnow
from app.config import settings
from app.db import get_conn
from app.errors import ApiError
from app.gate import require_deposit_allowed
from app.idempotency import Idempotent
from app import wallet
from app.payments import ProviderError, configured, service

router = APIRouter(tags=["payments"])


class DepositIn(BaseModel):
    amount_kobo: int = Field(gt=0, le=100_000_000)


@router.post("/wallet/deposits", status_code=201)
def deposit(body: DepositIn, request: Request, user=Depends(current_user),
            identity: Identity = Depends(current_identity), conn=Depends(get_conn), now=Depends(utcnow)):
    """Start a deposit: returns the provider's checkout link. Money is credited only after we verify it."""
    idem = Idempotent(conn, user["id"], request)
    if (prior := idem.replay()) is not None:
        return prior
    require_deposit_allowed(conn, user, now, body.amount_kobo)
    return idem.save(service.start_deposit(conn, user, body.amount_kobo, identity.email, now))


@router.get("/wallet/deposits/{reference}")
def deposit_status(reference: str, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    d = conn.execute("select user_id from deposits where psp_reference = %s", (reference,)).fetchone()
    if d is None or d["user_id"] != user["id"]:
        raise ApiError(404, "deposit_not_found", "deposit not found")
    d = service.settle_deposit(conn, reference, now)
    return {"reference": reference, "status": d["status"], "amount_kobo": d["amount_kobo"]}


@router.post("/payments/{provider}/webhook")
async def webhook(provider: str, request: Request, conn=Depends(get_conn), now=Depends(utcnow)):
    """Provider callbacks. No session: the signature is the authentication."""
    if provider not in ("paystack", "flutterwave"):
        raise ApiError(404, "unknown_provider", "unknown provider")
    raw = await request.body()
    try:
        return service.handle_webhook(conn, provider, raw, request.headers, now)
    except PermissionError:
        raise ApiError(401, "bad_signature", "signature check failed")


@router.get("/payments/banks")
def banks():
    for p in configured():
        try:
            return p.banks()
        except ProviderError:
            continue
    raise ApiError(502, "payments_down", "couldn't load the bank list")


class BankAccountIn(BaseModel):
    bank_code: str = Field(min_length=2, max_length=10)
    account_number: str = Field(pattern=r"^[0-9]{10}$")


@router.get("/me/bank-accounts")
def my_bank_accounts(user=Depends(current_user), conn=Depends(get_conn)):
    return conn.execute("""select id, bank_name, bank_code, account_name, right(account_number, 4) as last4
                           from bank_accounts where user_id = %s order by created_at""", (user["id"],)).fetchall()


@router.post("/me/bank-accounts", status_code=201)
def add_bank_account(body: BankAccountIn, user=Depends(current_user), conn=Depends(get_conn)):
    a = service.add_bank_account(conn, user, body.bank_code, body.account_number)
    return {"id": a["id"], "bank_name": a["bank_name"], "account_name": a["account_name"],
            "last4": a["account_number"][-4:]}


class WithdrawIn(BaseModel):
    amount_kobo: int = Field(gt=0, le=100_000_000)
    bank_account_id: UUID


@router.post("/wallet/withdrawals", status_code=201)
def withdraw(body: WithdrawIn, request: Request, user=Depends(current_user), conn=Depends(get_conn),
             now=Depends(utcnow)):
    idem = Idempotent(conn, user["id"], request)
    if (prior := idem.replay()) is not None:
        return prior
    w = service.request_withdrawal(conn, user, body.amount_kobo, body.bank_account_id, now)
    return idem.save(_w(w))


@router.get("/me/withdrawals")
def my_withdrawals(user=Depends(current_user), conn=Depends(get_conn)):
    return [_w(w) for w in conn.execute("select * from withdrawals where user_id = %s order by created_at desc "
                                        "limit 30", (user["id"],)).fetchall()]


def _w(w):
    return {k: w[k] for k in ("id", "amount_kobo", "status", "needs_approval", "failure_reason", "created_at",
                              "provider")}


# ---------- admin: approval queue and finance ----------

@router.get("/admin/withdrawals")
def withdrawal_queue(status: str = "awaiting_approval", user=Depends(require_admin), conn=Depends(get_conn)):
    return conn.execute(
        """select w.id, w.amount_kobo, w.status, w.created_at, w.failure_reason, u.team_name, u.id as user_id,
                  b.bank_name, b.account_name, right(b.account_number, 4) as last4,
                  (select count(*) from withdrawals x where x.user_id = w.user_id and x.status = 'paid') as paid_before
           from withdrawals w join users u on u.id = w.user_id left join bank_accounts b on b.id = w.bank_account_id
           where w.status = %s and (%s or u.school_id = %s) order by w.created_at""",
        (status, "superadmin" in user["roles"], user["school_id"])).fetchall()


def _queued(conn, user, withdrawal_id) -> dict:
    w = conn.execute("""select w.* from withdrawals w join users u on u.id = w.user_id where w.id = %s
                        and (%s or u.school_id = %s) for update of w""",
                     (withdrawal_id, "superadmin" in user["roles"], user["school_id"])).fetchone()
    if w is None:
        raise ApiError(404, "withdrawal_not_found", "withdrawal not found")
    if w["status"] != "awaiting_approval":
        raise ApiError(409, "not_awaiting_approval", f"this withdrawal is {w['status']}")
    return w


@router.post("/admin/withdrawals/{withdrawal_id}/approve")
def approve_withdrawal(withdrawal_id: UUID, user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    w = _queued(conn, user, withdrawal_id)
    conn.execute("update withdrawals set approved_by = %s where id = %s", (user["id"], w["id"]))
    audit(conn, user["id"], "withdrawal.approve", "withdrawal", w["id"])
    return _w(service.send_withdrawal(conn, w, now))


@router.post("/admin/withdrawals/{withdrawal_id}/reject")
def reject_withdrawal(withdrawal_id: UUID, user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    w = _queued(conn, user, withdrawal_id)
    wallet.release(conn, wallet.open_hold(conn, "withdrawal", w["id"]), now, "withdrawal_reversal")
    w = conn.execute("update withdrawals set status = 'rejected', approved_by = %s, updated_at = %s where id = %s "
                     "returning *", (user["id"], now, w["id"])).fetchone()
    audit(conn, user["id"], "withdrawal.reject", "withdrawal", w["id"])
    return _w(w)


@router.get("/admin/finance")
def finance(user=Depends(require_admin), conn=Depends(get_conn), now=Depends(utcnow)):
    """Money at a glance (platform-wide; superadmins only see everything, admins see the same totals)."""
    sums = {r["k"]: r["n"] for r in conn.execute(
        """select case when account like 'user:%%:cash' then 'cash' when account like 'user:%%:bonus' then 'coins'
                       when account like 'user:%%:held%%' then 'held' when account like '%%:pot' then 'pots'
                       else account end as k, sum(amount_kobo)::bigint as n
           from wallet_ledger group by 1""").fetchall()}
    day = conn.execute(
        """select coalesce(sum(amount_kobo) filter (where status = 'success'), 0)::bigint as deposits,
                  count(*) filter (where status = 'pending') as pending
           from deposits where created_at > %s - interval '24 hours'""", (now,)).fetchone()
    out = conn.execute(
        """select coalesce(sum(amount_kobo) filter (where status = 'paid'), 0)::bigint as paid,
                  count(*) filter (where status = 'awaiting_approval') as awaiting
           from withdrawals where created_at > %s - interval '24 hours'""", (now,)).fetchone()
    return {"player_cash_kobo": sums.get("cash", 0), "player_coins_kobo": sums.get("coins", 0),
            "held_kobo": sums.get("held", 0), "in_pots_kobo": sums.get("pots", 0),
            "platform_fee_kobo": sums.get(wallet.PLATFORM_FEE, 0), "coins_issued_kobo": -sums.get(wallet.BONUS_POOL, 0),
            "deposits_24h_kobo": day["deposits"], "deposits_pending": day["pending"],
            "withdrawals_paid_24h_kobo": out["paid"], "withdrawals_awaiting": out["awaiting"],
            "ledger": wallet.ledger_check(conn), "paid_play_enabled": settings.paid_play_enabled}
