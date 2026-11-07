"""Referral coins (stake-only) for both players once the invited friend has deposited at least
REFERRAL_MIN_DEPOSIT: with KYC on, after the friend is ID-verified; with KYC optional, when that deposit
came from a bank account no other player has paid in from. Checked after a KYC pass and each deposit."""
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


def _fresh_funding_account(conn, user_id) -> bool:
    """KYC optional: the friend has paid in at least the minimum from a bank account (last four digits +
    holder name) that no other CampusXI player has paid in from, so one person can't farm coins."""
    from app.payments.service import name_matches
    mine = conn.execute("""select payer_account_tail, payer_name from deposits where user_id = %s and status = 'success'
                           and amount_kobo >= %s and payer_account_tail is not null and payer_name is not null""",
                        (user_id, settings.referral_min_deposit_kobo)).fetchall()
    for d in mine:
        others = conn.execute("""select payer_name from deposits where user_id <> %s and status = 'success'
                                 and payer_account_tail = %s and payer_name is not null""",
                              (user_id, d["payer_account_tail"])).fetchall()
        if not any(name_matches(o["payer_name"], d["payer_name"]) for o in others):
            return True
    return False


def maybe_reward(conn, user_id, now) -> bool:
    u = conn.execute("select id, referred_by, kyc_status from users where id = %s", (user_id,)).fetchone()
    if not u or not u["referred_by"]:
        return False
    if settings.kyc_required and u["kyc_status"] != "verified":
        return False
    if conn.execute("select 1 from referrals where referred_id = %s", (user_id,)).fetchone():
        return False
    if settings.kyc_required:
        deposited = conn.execute("""select coalesce(max(amount_kobo), 0) as m from deposits
                                    where user_id = %s and status = 'success'""", (user_id,)).fetchone()["m"]
        if deposited < settings.referral_min_deposit_kobo:
            return False
    elif not _fresh_funding_account(conn, user_id):
        return False
    conn.execute(
        """insert into referrals (referrer_id, referred_id, bonus_kobo, referred_bonus_kobo, credited_at)
           values (%s, %s, %s, %s, %s)""",
        (u["referred_by"], user_id, settings.referral_bonus_kobo, settings.referred_bonus_kobo, now))
    grant_bonus(conn, u["referred_by"], settings.referral_bonus_kobo, "referral", now)
    grant_bonus(conn, user_id, settings.referred_bonus_kobo, "welcome", now)
    return True
