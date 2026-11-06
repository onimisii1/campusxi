"""Referral coins: once an invited friend is ID-verified and has deposited at least
REFERRAL_MIN_DEPOSIT, both get coins (stake-only). Checked after a KYC pass and after each deposit."""
import secrets

from app.config import settings
from app.wallet import grant_bonus

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I mix-ups when read aloud


def ensure_code(conn, user_id) -> str:
    row = conn.execute("select referral_code from users where id = %s", (user_id,)).fetchone()
    if row["referral_code"]:
        return row["referral_code"]
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        if not conn.execute("select 1 from users where referral_code = %s", (code,)).fetchone():
            conn.execute("update users set referral_code = %s where id = %s", (code, user_id))
            return code


def maybe_reward(conn, user_id, now) -> bool:
    u = conn.execute("select id, referred_by, kyc_status from users where id = %s", (user_id,)).fetchone()
    if not u or not u["referred_by"] or u["kyc_status"] != "verified":
        return False
    if conn.execute("select 1 from referrals where referred_id = %s", (user_id,)).fetchone():
        return False
    deposited = conn.execute("""select coalesce(max(amount_kobo), 0) as m from deposits
                                where user_id = %s and status = 'success'""", (user_id,)).fetchone()["m"]
    if deposited < settings.referral_min_deposit_kobo:
        return False
    conn.execute(
        """insert into referrals (referrer_id, referred_id, bonus_kobo, referred_bonus_kobo, credited_at)
           values (%s, %s, %s, %s, %s)""",
        (u["referred_by"], user_id, settings.referral_bonus_kobo, settings.referred_bonus_kobo, now))
    grant_bonus(conn, u["referred_by"], settings.referral_bonus_kobo, "referral", now)
    grant_bonus(conn, user_id, settings.referred_bonus_kobo, "welcome", now)
    return True
