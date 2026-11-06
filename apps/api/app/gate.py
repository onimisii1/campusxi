"""Who may play for money, and how much (PRD A3, G4: KYC, 18+, responsible-gaming limits).

Limits follow the usual rule: lowering a limit (or excluding yourself) takes effect at once;
raising it only after 24 hours, so a bad night can't be chased.
"""
from datetime import timedelta

from app.config import settings
from app.errors import ApiError
from app.routers.me import age_on

LIMIT_KINDS = ("deposit_limit", "stake_limit")
COOLING_OFF = timedelta(hours=24)


def self_excluded_until(conn, user_id, now):
    row = conn.execute("""select max(until) as u from exclusions where user_id = %s and kind = 'self_exclusion'
                          and until > %s""", (user_id, now)).fetchone()
    return row["u"]


def effective_limit(conn, user_id, kind: str, now, default: int | None) -> int | None:
    """The tightest of: the newest limit that is at least 24h old (or the default), and every limit
    set in the last 24 hours."""
    rows = conn.execute("select value_kobo, created_at from exclusions where user_id = %s and kind = %s "
                        "order by created_at", (user_id, kind)).fetchall()
    settled = [r["value_kobo"] for r in rows if r["created_at"] <= now - COOLING_OFF]
    base = settled[-1] if settled else default
    recent = [r["value_kobo"] for r in rows if r["created_at"] > now - COOLING_OFF]
    values = [v for v in [base, *recent] if v is not None]
    return min(values) if values else None


def spent_today(conn, user_id, now) -> dict:
    day = now - timedelta(hours=24)
    stakes = conn.execute(
        """select coalesce(sum(cash_kobo + bonus_kobo), 0)::bigint as n from wallet_holds where user_id = %s
           and ref_type in ('contest_entry', 'bet', 'bet_fill') and created_at > %s""", (user_id, day)).fetchone()["n"]
    deposits = conn.execute(
        """select coalesce(sum(amount_kobo), 0)::bigint as n from deposits where user_id = %s and created_at > %s
           and status in ('pending', 'success')""", (user_id, day)).fetchone()["n"]
    return {"stakes": stakes, "deposits": deposits}


def limits(conn, user_id, now) -> dict:
    used = spent_today(conn, user_id, now)
    return {
        "daily_deposit_kobo": effective_limit(conn, user_id, "deposit_limit", now, settings.daily_deposit_limit_kobo),
        "daily_stake_kobo": effective_limit(conn, user_id, "stake_limit", now, None),
        "deposited_today_kobo": used["deposits"], "staked_today_kobo": used["stakes"],
        "self_excluded_until": self_excluded_until(conn, user_id, now),
    }


def require_paid_play(conn, user: dict, now, amount: int = 0, result_bet: bool = False) -> None:
    """Raise unless this user may put `amount` kobo at stake right now."""
    if not settings.paid_play_enabled:
        raise ApiError(403, "paid_play_unavailable", "paid contests and stakes aren't open yet")
    if result_bet and not settings.result_bets_enabled:
        raise ApiError(403, "result_bets_unavailable", "Home/Away bets aren't open yet")
    if user["kyc_status"] != "verified":
        raise ApiError(403, "kyc_required", "verify your ID (NIN or BVN) before playing for money")
    if age_on(user["dob"], now.date()) < 18:
        raise ApiError(403, "under_18", "CampusXI is for players aged 18 and over")
    until = self_excluded_until(conn, user["id"], now)
    if until:
        raise ApiError(403, "self_excluded", f"you've taken a break from paid play until {until:%d %b %Y}")
    lim = limits(conn, user["id"], now)
    if lim["daily_stake_kobo"] is not None and lim["staked_today_kobo"] + amount > lim["daily_stake_kobo"]:
        raise ApiError(403, "stake_limit", "that would go over the daily stake limit you set")


def require_deposit_allowed(conn, user: dict, now, amount: int) -> None:
    if user["kyc_status"] != "verified":
        raise ApiError(403, "kyc_required", "verify your ID (NIN or BVN) before adding money")
    if self_excluded_until(conn, user["id"], now):
        raise ApiError(403, "self_excluded", "you've taken a break from paid play")
    if amount < settings.min_deposit_kobo:
        raise ApiError(422, "below_minimum", f"the smallest deposit is ₦{settings.min_deposit_kobo / 100:,.0f}")
    lim = limits(conn, user["id"], now)
    if lim["daily_deposit_kobo"] is not None and lim["deposited_today_kobo"] + amount > lim["daily_deposit_kobo"]:
        raise ApiError(403, "deposit_limit", f"that would go over your daily deposit limit of "
                                             f"₦{lim['daily_deposit_kobo'] / 100:,.0f}")
