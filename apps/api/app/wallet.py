"""The wallet: the only code that moves money. Everything is a balanced wallet_ledger transaction
(append-only, checked at commit by the wallet_ledger_balanced trigger) in integer kobo.

Users have four accounts: cash (withdrawable), bonus (referral coins: stake-only), and the held
versions of each. A hold moves money from cash/bonus into held and records the split in
wallet_holds, so it can be released back to exactly where it came from, or captured into a pot.
Pots (contest:{id}:pot, bet:{id}:pot) are paid out as prizes (always cash) and platform fee.

Per-user advisory locks serialise balance checks, so two taps can't spend the same naira twice.
"""
import uuid
from datetime import timedelta

from app.config import settings
from app.errors import ApiError

CASH, BONUS, HELD_CASH, HELD_BONUS = "cash", "bonus", "held_cash", "held_bonus"
PLATFORM_FEE = "platform:fee"
BONUS_POOL = "platform:bonus_pool"


def acct(user_id, kind: str) -> str:
    return f"user:{user_id}:{kind}"


def pot(ref_type: str, ref_id) -> str:
    return f"{ref_type}:{ref_id}:pot"


def psp(provider: str) -> str:
    return f"psp:{provider}:clearing"


def lock_user(conn, user_id) -> None:
    conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"wallet:{user_id}",))


def balance(conn, account: str) -> int:
    return conn.execute("select coalesce(sum(amount_kobo), 0)::bigint as b from wallet_ledger where account = %s",
                        (account,)).fetchone()["b"]


def balances(conn, user_id) -> dict:
    rows = conn.execute(
        """select account, coalesce(sum(amount_kobo), 0)::bigint as b from wallet_ledger
           where account like %s group by account""", (f"user:{user_id}:%",)).fetchall()
    got = {r["account"].rsplit(":", 1)[1]: r["b"] for r in rows}
    return {k: got.get(k, 0) for k in (CASH, BONUS, HELD_CASH, HELD_BONUS)}


def post(conn, lines, ref_type: str | None = None, ref_id=None) -> uuid.UUID:
    """One balanced transaction. lines: [(account, amount_kobo, entry_type)]; zero lines are skipped."""
    lines = [ln for ln in lines if ln[1]]
    if not lines:
        return None
    if sum(amount for _, amount, _ in lines) != 0:
        raise AssertionError(f"unbalanced wallet transaction: {lines}")
    txn = uuid.uuid4()
    with conn.cursor() as cur:
        cur.executemany(
            """insert into wallet_ledger (txn_id, account, amount_kobo, entry_type, ref_type, ref_id)
               values (%s, %s, %s, %s, %s, %s)""",
            [(txn, account, amount, etype, ref_type, ref_id) for account, amount, etype in lines])
    return txn


# ---------- money in ----------

def credit_deposit(conn, user_id, amount: int, provider: str, deposit_id) -> None:
    post(conn, [(psp(provider), -amount, "deposit"), (acct(user_id, CASH), amount, "deposit")],
         "deposit", deposit_id)


def grant_bonus(conn, user_id, amount: int, reason: str, now) -> None:
    """Referral coins: funded by the platform's bonus pool, stake-only, expire after BONUS_EXPIRY_DAYS."""
    g = conn.execute(
        """insert into bonus_grants (user_id, amount_kobo, reason, expires_at) values (%s, %s, %s, %s)
           returning id""", (user_id, amount, reason, now + timedelta(days=settings.bonus_expiry_days))).fetchone()
    post(conn, [(BONUS_POOL, -amount, "bonus"), (acct(user_id, BONUS), amount, "bonus")], "bonus_grant", g["id"])


# ---------- holds ----------

def hold(conn, user_id, amount: int, ref_type: str, ref_id, use_bonus: bool = True) -> dict:
    """Hold `amount` for an entry/stake: coins first, up to BONUS_MAX_SHARE of it, then cash.
    Raises 402 insufficient_funds if cash can't cover the rest."""
    lock_user(conn, user_id)
    have = balances(conn, user_id)
    from_bonus = min(have[BONUS], amount * settings.bonus_max_share_bps // 10000) if use_bonus else 0
    from_cash = amount - from_bonus
    if from_cash > have[CASH]:
        raise ApiError(402, "insufficient_funds", f"you need ₦{(from_cash - have[CASH]) / 100:,.0f} more in your "
                                                   f"wallet", {"short_kobo": from_cash - have[CASH]})
    h = conn.execute(
        """insert into wallet_holds (user_id, ref_type, ref_id, cash_kobo, bonus_kobo) values (%s, %s, %s, %s, %s)
           returning *""", (user_id, ref_type, ref_id, from_cash, from_bonus)).fetchone()
    post(conn, [(acct(user_id, CASH), -from_cash, "hold"), (acct(user_id, HELD_CASH), from_cash, "hold"),
                (acct(user_id, BONUS), -from_bonus, "hold"), (acct(user_id, HELD_BONUS), from_bonus, "hold")],
         ref_type, ref_id)
    return h


def open_hold(conn, ref_type: str, ref_id) -> dict | None:
    return conn.execute("select * from wallet_holds where ref_type = %s and ref_id = %s and status = 'held' "
                        "for update", (ref_type, ref_id)).fetchone()


def release(conn, h: dict, now, entry_type: str = "release") -> None:
    """Give held money back where it came from (cash to cash, coins to coins)."""
    u = h["user_id"]
    post(conn, [(acct(u, HELD_CASH), -h["cash_kobo"], entry_type), (acct(u, CASH), h["cash_kobo"], entry_type),
                (acct(u, HELD_BONUS), -h["bonus_kobo"], entry_type), (acct(u, BONUS), h["bonus_kobo"], entry_type)],
         h["ref_type"], h["ref_id"])
    conn.execute("update wallet_holds set status = 'released', closed_at = %s where id = %s", (now, h["id"]))


def capture(conn, h: dict, into: str, entry_type: str, now) -> int:
    """Move a hold into a pot (entry fee or stake). Coins become pot money: the bonus pool funded them."""
    u = h["user_id"]
    total = h["cash_kobo"] + h["bonus_kobo"]
    post(conn, [(acct(u, HELD_CASH), -h["cash_kobo"], entry_type), (acct(u, HELD_BONUS), -h["bonus_kobo"], entry_type),
                (into, total, entry_type)], h["ref_type"], h["ref_id"])
    conn.execute("update wallet_holds set status = 'captured', closed_at = %s where id = %s", (now, h["id"]))
    return total


def pay_out(conn, pot_account: str, prizes: dict, platform_kobo: int, ref_type: str, ref_id,
            prize_type: str = "prize", fee_type: str = "rake") -> None:
    """Empty a pot: prizes to users' cash (always cash, even if they staked coins) and the rest as fee."""
    lines = [(acct(u, CASH), amount, prize_type) for u, amount in prizes.items() if amount]
    lines.append((PLATFORM_FEE, platform_kobo, fee_type))
    lines.append((pot_account, -(sum(prizes.values()) + platform_kobo), prize_type))
    post(conn, lines, ref_type, ref_id)
    left = balance(conn, pot_account)
    if left != 0:
        raise AssertionError(f"{pot_account} not empty after payout ({left})")


def refund_pot(conn, pot_account: str, holds: list, now, ref_type: str, ref_id) -> None:
    """Undo captures: give each hold's money back to its source (coins back as coins)."""
    lines = []
    for h in holds:
        u = h["user_id"]
        lines += [(acct(u, CASH), h["cash_kobo"], "refund"), (acct(u, BONUS), h["bonus_kobo"], "refund"),
                  (pot_account, -(h["cash_kobo"] + h["bonus_kobo"]), "refund")]
    post(conn, lines, ref_type, ref_id)


# ---------- money out ----------

def hold_withdrawal(conn, user_id, amount: int, withdrawal_id) -> dict:
    """Withdrawals come from cash only (coins can't be withdrawn)."""
    return hold(conn, user_id, amount, "withdrawal", withdrawal_id, use_bonus=False)


def complete_withdrawal(conn, h: dict, provider: str, now) -> None:
    u = h["user_id"]
    post(conn, [(acct(u, HELD_CASH), -h["cash_kobo"], "withdrawal"), (psp(provider), h["cash_kobo"], "withdrawal")],
         "withdrawal", h["ref_id"])
    conn.execute("update wallet_holds set status = 'captured', closed_at = %s where id = %s", (now, h["id"]))


def expire_bonus(conn, now) -> int:
    """Coins past their expiry go back to the pool (only what's still unspent and not held)."""
    expired = 0
    for g in conn.execute("select * from bonus_grants where expires_at <= %s and expired_at is null for update",
                          (now,)).fetchall():
        lock_user(conn, g["user_id"])
        live = conn.execute("""select coalesce(sum(amount_kobo), 0)::bigint as n from bonus_grants
                               where user_id = %s and expired_at is null and expires_at > %s""",
                            (g["user_id"], now)).fetchone()["n"]
        over = max(0, balances(conn, g["user_id"])[BONUS] - live)   # coins not backed by an unexpired grant
        take = min(over, g["amount_kobo"])
        post(conn, [(acct(g["user_id"], BONUS), -take, "bonus_expiry"), (BONUS_POOL, take, "bonus_expiry")],
             "bonus_grant", g["id"])
        conn.execute("update bonus_grants set expired_at = %s where id = %s", (now, g["id"]))
        expired += take
    return expired


def ledger_check(conn) -> dict:
    """Whole-ledger sanity: everything sums to zero and no user account is negative."""
    total = conn.execute("select coalesce(sum(amount_kobo), 0)::bigint as t from wallet_ledger").fetchone()["t"]
    negative = conn.execute(
        """select account, sum(amount_kobo)::bigint as b from wallet_ledger where account like 'user:%%'
           group by account having sum(amount_kobo) < 0""").fetchall()
    return {"balanced": total == 0, "total_kobo": total, "negative_accounts": negative}
