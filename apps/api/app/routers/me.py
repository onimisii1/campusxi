"""Profile creation (PRD A1, A2): permanent team name, school, and a declared 18+ date of birth."""
import secrets

import httpx
from fastapi import APIRouter, Depends

from app.audit import audit
from app.auth import Identity, current_identity, current_user
from app.clock import utcnow
from app.config import settings
from app.db import get_conn
from app.errors import ApiError
from app.schemas import ProfileIn

router = APIRouter(tags=["me"])


def age_on(dob, today) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


@router.post("/me", status_code=201)
def create_profile(body: ProfileIn, identity: Identity = Depends(current_identity),
                   conn=Depends(get_conn), now=Depends(utcnow)):
    if conn.execute("select 1 from users where id = %s", (identity.user_id,)).fetchone():
        raise ApiError(409, "profile_exists", "you already have a profile")
    if age_on(body.dob, now.date()) < 18:
        raise ApiError(422, "under_18", "CampusXI is for players aged 18 and over")
    if not conn.execute("select 1 from schools where id = %s", (body.school_id,)).fetchone():
        raise ApiError(422, "unknown_school", "choose a school from the list")
    if conn.execute("select 1 from users where lower(team_name) = lower(%s)", (body.team_name,)).fetchone():
        raise ApiError(409, "team_name_taken", "that team name is taken")
    # created_at comes from the same clock as the age check, so the DB's 18+ constraint agrees.
    conn.execute(
        "insert into users (id, school_id, team_name, dob, created_at) values (%s, %s, %s, %s, %s)",
        (identity.user_id, body.school_id, body.team_name.strip(), body.dob, now),
    )
    from app.routers.wallet import apply_referral_code
    apply_referral_code(conn, identity.user_id, body.referral_code)
    return conn.execute("select * from users where id = %s", (identity.user_id,)).fetchone()


@router.get("/me")
def get_profile(user: dict = Depends(current_user)):
    return user


def _delete_sign_in(user_id) -> None:
    """Remove the player's Supabase sign-in (email) with the server-only key."""
    if not settings.supabase_url:          # local development / tests: no Supabase sign-in to remove
        return
    if not settings.supabase_service_role_key:
        raise ApiError(503, "deletion_unavailable", "account deletion isn't set up yet; contact support")
    key = settings.supabase_service_role_key
    try:
        res = httpx.delete(f"{settings.supabase_url}/auth/v1/admin/users/{user_id}", timeout=15,
                           headers={"apikey": key, "Authorization": f"Bearer {key}"})
    except httpx.HTTPError:
        raise ApiError(502, "deletion_failed", "couldn't reach the sign-in service; nothing was deleted, try again")
    if res.status_code not in (200, 204, 404):
        raise ApiError(502, "deletion_failed", "the sign-in service refused; nothing was deleted, try again")


@router.delete("/me")
def delete_account(user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    """Delete the account (NDPA right to erasure). Personal details go; money and match records stay,
    anonymised, as financial rules require. Cash must be withdrawn and nothing left in play first."""
    from app import wallet
    wallet.lock_user(conn, user["id"])
    b = wallet.balances(conn, user["id"])
    if b[wallet.CASH] > 0:
        raise ApiError(409, "withdraw_first", f"withdraw your ₦{b[wallet.CASH] / 100:,.0f} first; "
                                              "deleting the account would lose it", {"cash_kobo": b[wallet.CASH]})
    if b[wallet.HELD_CASH] + b[wallet.HELD_BONUS] > 0 or conn.execute(
            "select 1 from withdrawals where user_id = %s and status in ('awaiting_approval', 'pending')",
            (user["id"],)).fetchone():
        raise ApiError(409, "money_in_play", "you have entries, stakes or a withdrawal still in progress; "
                                             "delete the account once they've finished")
    if b[wallet.BONUS] > 0:      # coins are forfeited (they were never cash)
        wallet.post(conn, [(wallet.acct(user["id"], wallet.BONUS), -b[wallet.BONUS], "bonus_expiry"),
                           (wallet.BONUS_POOL, b[wallet.BONUS], "bonus_expiry")], "account_deletion", user["id"])
    # Free contest entries and open free challenges for matches that haven't started go too.
    conn.execute("""delete from contest_entries e using contests c, matches m
                    where e.contest_id = c.id and c.match_id = m.id and e.user_id = %s and c.entry_fee_kobo = 0
                      and m.status in ('scheduled', 'lineup_out') and m.scheduled_start > %s""", (user["id"], now))
    conn.execute("update p2p_bets set status = 'cancelled' where creator_id = %s and status = 'open' and stake_kobo = 0",
                 (user["id"],))
    conn.execute("delete from media where owner_id = %s and kind = 'avatar'", (user["id"],))
    conn.execute(
        """update users set team_name = %s, avatar_url = null, referral_code = null, device_fingerprint = null,
                            legal_name = null,
                            roles = '{player}', deleted_at = %s where id = %s""",
        (f"deleted_{secrets.token_hex(4)}", now, user["id"]))
    audit(conn, user["id"], "account.delete", "user", user["id"])
    _delete_sign_in(user["id"])      # last: if this fails, the whole deletion is rolled back
    return {"deleted": True}
