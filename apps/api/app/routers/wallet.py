"""The player's money pages: balance and history, ID check, limits and breaks, referral code."""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.audit import audit
from app.auth import current_user
from app.clock import utcnow
from app.config import settings
from app.db import get_conn
from app.errors import ApiError
from app.gate import identity_ok, limits
from app.kyc import identity_hash, provider
from app.referrals import ensure_code, maybe_reward
from app.routers.me import age_on
from app.wallet import BONUS, CASH, HELD_BONUS, HELD_CASH, balances

router = APIRouter(tags=["wallet"])

ENTRY_LABELS = {
    "deposit": "Deposit", "withdrawal": "Withdrawal", "withdrawal_reversal": "Withdrawal returned",
    "hold": "Entry / stake held", "release": "Returned", "refund": "Refund", "prize": "Winnings",
    "payout": "Winnings", "bonus": "Bonus coins", "bonus_expiry": "Coins expired",
}


@router.get("/me/wallet")
def my_wallet(user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    b = balances(conn, user["id"])
    expiring = conn.execute(
        """select min(expires_at) as at from bonus_grants where user_id = %s and expired_at is null
           and expires_at > %s""", (user["id"], now)).fetchone()["at"]
    return {"cash_kobo": b[CASH], "bonus_kobo": b[BONUS], "held_kobo": b[HELD_CASH] + b[HELD_BONUS],
            "bonus_expires_at": expiring if b[BONUS] else None, "kyc_status": user["kyc_status"],
            "paid_play_enabled": settings.paid_play_enabled, "result_bets_enabled": settings.result_bets_enabled,
            "bonus_max_share_bps": settings.bonus_max_share_bps,
            "min_deposit_kobo": settings.min_deposit_kobo, "min_withdrawal_kobo": settings.min_withdrawal_kobo,
            "limits": limits(conn, user["id"], now),
            # KYC optional for now: the 18+ tick box, bank transfer only, and the bank name taken (and locked)
            # from the first bank-transfer deposit; only an admin can correct it.
            "kyc_required": settings.kyc_required, "can_play_paid": identity_ok(user),
            "adult_confirmed": user["adult_confirmed_at"] is not None, "legal_name": user["legal_name"],
            "legal_name_locked": user["legal_name"] is not None,
            "deposit_methods": ["card", "bank", "ussd", "bank_transfer"] if settings.kyc_required else ["bank_transfer"]}


class AdultIn(BaseModel):
    confirm: Literal[True]


@router.post("/me/confirm-18")
def confirm_adult(body: AdultIn, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """The "I'm 18 or older" tick box that stands in for an ID check while KYC is optional."""
    if user["adult_confirmed_at"] is None:
        conn.execute("update users set adult_confirmed_at = %s where id = %s", (now, user["id"]))
        audit(conn, user["id"], "user.confirm_18", "user", user["id"])
    return {"adult_confirmed": True}


@router.get("/me/wallet/history")
def wallet_history(limit: int = 50, user=Depends(current_user), conn=Depends(get_conn)):
    """What changed the player's cash and coins, newest first (held money moves are folded in)."""
    rows = conn.execute(
        """select txn_id, min(created_at) as at, min(entry_type) as entry_type, min(ref_type) as ref_type,
                  min(ref_id::text) as ref_id,
                  sum(amount_kobo) filter (where account = %(cash)s)::bigint as cash,
                  sum(amount_kobo) filter (where account = %(bonus)s)::bigint as bonus
           from wallet_ledger where account in (%(cash)s, %(bonus)s)
           group by txn_id order by at desc limit %(limit)s""",
        {"cash": f"user:{user['id']}:{CASH}", "bonus": f"user:{user['id']}:{BONUS}", "limit": min(limit, 200)},
    ).fetchall()
    return [{"at": r["at"], "type": r["entry_type"], "label": ENTRY_LABELS.get(r["entry_type"], r["entry_type"]),
             "ref_type": r["ref_type"], "ref_id": r["ref_id"], "cash_kobo": r["cash"] or 0,
             "bonus_kobo": r["bonus"] or 0} for r in rows]


class KycIn(BaseModel):
    id_type: Literal["nin", "bvn"]
    number: str = Field(pattern=r"^[0-9]{11}$")
    full_name: str = Field(min_length=3, max_length=80)


@router.post("/me/kyc")
def verify_id(body: KycIn, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """Check the player's NIN or BVN. Only the last four digits and a salted hash are stored."""
    if user["kyc_status"] == "verified":
        return {"status": "verified"}
    digest = identity_hash(body.id_type, body.number)
    if conn.execute("""select 1 from kyc_records where identity_hash = %s and status = 'verified'
                       and user_id <> %s""", (digest, user["id"])).fetchone():
        status, reason, result = "rejected", "this ID is already verified on another account", None
    else:
        result = provider().verify(body.id_type, body.number, user["dob"], body.full_name.strip())
        status, reason = result.status, result.reason
        if status == "verified" and result.dob and age_on(result.dob, now.date()) < 18:
            status, reason = "rejected", "the ID shows you're under 18"
    conn.execute(
        """insert into kyc_records (user_id, provider, provider_ref, verified_name, dob, status, id_type, id_last4,
                                    identity_hash, reason) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (user["id"], provider().name, result.reference if result else "duplicate",
         result.verified_name if result else None, result.dob if result else None, status, body.id_type,
         body.number[-4:], digest, reason))
    conn.execute("update users set kyc_status = %s where id = %s", (status, user["id"]))
    audit(conn, user["id"], "kyc.check", "user", user["id"], status=status, id_type=body.id_type)
    if status == "verified":
        maybe_reward(conn, user["id"], now)
    return {"status": status, "reason": reason}


class LimitsIn(BaseModel):
    daily_deposit_kobo: int | None = Field(default=None, ge=0, le=100_000_000)
    daily_stake_kobo: int | None = Field(default=None, ge=0, le=100_000_000)


@router.put("/me/limits")
def set_limits(body: LimitsIn, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """Lower limits apply now; higher ones after 24 hours."""
    for kind, value in (("deposit_limit", body.daily_deposit_kobo), ("stake_limit", body.daily_stake_kobo)):
        if value is not None:
            conn.execute("insert into exclusions (user_id, kind, value_kobo, created_at) values (%s, %s, %s, %s)",
                         (user["id"], kind, value, now))
    audit(conn, user["id"], "limits.set", "user", user["id"], **body.model_dump(exclude_none=True))
    return limits(conn, user["id"], now)


class BreakIn(BaseModel):
    days: int = Field(ge=1, le=3650)


@router.post("/me/self-exclusion")
def take_a_break(body: BreakIn, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """No paid play or deposits until the date; it can't be undone early."""
    until = now + timedelta(days=body.days)
    conn.execute("insert into exclusions (user_id, kind, until, created_at) values (%s, 'self_exclusion', %s, %s)",
                 (user["id"], until, now))
    audit(conn, user["id"], "self_exclusion", "user", user["id"], days=body.days)
    return {"self_excluded_until": until}


@router.get("/me/referral")
def my_referral(user=Depends(current_user), conn=Depends(get_conn)):
    code = ensure_code(conn, user["id"])
    rows = conn.execute("""select count(*) as n, coalesce(sum(bonus_kobo), 0)::bigint as coins from referrals
                           where referrer_id = %s""", (user["id"],)).fetchone()
    waiting = conn.execute("""select count(*) as n from users u where u.referred_by = %s and not exists
                              (select 1 from referrals r where r.referred_id = u.id)""", (user["id"],)).fetchone()["n"]
    return {"code": code, "link": f"{settings.public_app_url}/#/join/{code}", "friends_rewarded": rows["n"],
            "friends_waiting": waiting, "coins_earned_kobo": rows["coins"],
            "reward_kobo": settings.referral_bonus_kobo, "friend_reward_kobo": settings.referred_bonus_kobo,
            "min_deposit_kobo": settings.referral_min_deposit_kobo}


def apply_referral_code(conn, user_id, code: str | None) -> None:
    """Called when a profile is created with a friend's code."""
    if not code:
        return
    ref = conn.execute("select id from users where referral_code = upper(%s)", (code.strip(),)).fetchone()
    if ref is None:
        raise ApiError(422, "unknown_referral", "that referral code doesn't exist")
    if ref["id"] != user_id:
        conn.execute("update users set referred_by = %s where id = %s", (ref["id"], user_id))
