"""P2P challenges (PRD 5.8, 8.5, 6.11-6.12).

Fantasy H2H: your team against one other player's, free or for a stake (N1,000 minimum; the winner
gets both stakes less 10% commission on the winnings). Home/Away result bets: back a side; any number
of challengers take the other side in slices until the stake is matched (licence flag:
RESULT_BETS_ENABLED). Stakes are held in the wallet when posted or accepted and settled after the
result is confirmed (app/settlement.py). The creator's fantasy team stays hidden until kick-off.
"""
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import current_user, optional_user
from app.clock import utcnow
from app.config import settings
from app.db import get_conn
from app import wallet
from app.engines.p2p import (FANTASY_H2H, MATCH_RESULT, Bet, Fill, opposite, quote_creator,
                            quote_fill, validate_fill, validate_new_bet)
from app.gate import require_paid_play
from app.idempotency import Idempotent
from app.errors import ApiError
from app.fantasy import team_totals
from app.live import official_or_primary_scorer, stream_scores
from app.matches import assert_open, is_locked, load_match
from app.routers.contests import assert_not_scorer
from app.settlement import bet_event

router = APIRouter(tags=["challenges"])


class BetIn(BaseModel):
    kind: Literal["fantasy_h2h", "match_result"] = "fantasy_h2h"
    match_id: UUID
    fantasy_team_id: UUID | None = None       # fantasy H2H only
    side: Literal["home", "away"] | None = None  # result bets only
    stake_kobo: int = Field(default=0, ge=0, le=100_000_000)
    visibility: Literal["board", "direct"] = "board"


class FillIn(BaseModel):
    fantasy_team_id: UUID | None = None
    amount_kobo: int | None = Field(default=None, gt=0)   # result bets: your slice (default: all that's left)


OPEN_FOR_FILLS = ("open", "partially_matched")


def linked_users(conn, user_id) -> set:
    """Accounts that look like the same person: same bank account or same device."""
    rows = conn.execute(
        """select distinct b2.user_id as id from bank_accounts b1 join bank_accounts b2
             on b2.bank_code = b1.bank_code and b2.account_number = b1.account_number and b2.user_id <> b1.user_id
           where b1.user_id = %(u)s
           union
           select u2.id from users u1 join users u2 on u2.device_fingerprint = u1.device_fingerprint and u2.id <> u1.id
           where u1.id = %(u)s and u1.device_fingerprint is not null""", {"u": user_id}).fetchall()
    return {str(r["id"]) for r in rows}


def _bet_model(conn, b) -> Bet:
    fills = tuple(Fill(str(f["challenger_id"]), f["amount_kobo"]) for f in conn.execute(
        "select challenger_id, amount_kobo from p2p_bet_fills where bet_id = %s order by created_at, id",
        (b["id"],)).fetchall())
    return Bet(b["kind"], str(b["creator_id"]), b["stake_kobo"], b["creator_side"], fills, b["commission_bps"])


def _own_team(conn, user, team_id, match_id) -> dict:
    team = conn.execute("select * from fantasy_teams where id = %s and user_id = %s",
                        (team_id, user["id"])).fetchone()
    if team is None or team["match_id"] != match_id:
        raise ApiError(422, "wrong_team", "use one of your teams for this match")
    return team


def _records(conn, user_ids) -> dict:
    """{user_id: {won, lost, tied}} from settled challenges."""
    out = {u: {"won": 0, "lost": 0, "tied": 0} for u in user_ids}
    rows = conn.execute(
        """select b.creator_id, f.challenger_id, b.outcome from p2p_bets b join p2p_bet_fills f on f.bet_id = b.id
           where b.status = 'settled' and b.kind = 'fantasy_h2h'
             and (b.creator_id = any(%(u)s) or f.challenger_id = any(%(u)s))""", {"u": list(user_ids)}).fetchall()
    for r in rows:
        for uid, side in ((r["creator_id"], "creator"), (r["challenger_id"], "taker")):
            if uid in out:
                key = "tied" if r["outcome"] == "tie" else ("won" if r["outcome"] == side else "lost")
                out[uid][key] += 1
    return out


def _card(b, records, user) -> dict:
    unmatched = b["stake_kobo"] - b["matched_kobo"]
    return {"id": b["id"], "kind": b["kind"], "match_id": b["match_id"], "stake_kobo": b["stake_kobo"],
            "matched_kobo": b["matched_kobo"], "unmatched_kobo": unmatched, "side": b["creator_side"],
            "your_side": opposite(b["creator_side"]) if b["creator_side"] else None,
            "visibility": b["visibility"], "status": b["status"], "created_at": b["created_at"],
            "creator": {"team_name": b["team_name"], "record": records.get(b["creator_id"])},
            "win_up_to_kobo": quote_creator(b["stake_kobo"]) if b["stake_kobo"] else 0,
            "quote_kobo": quote_fill(Bet(b["kind"], str(b["creator_id"]), b["stake_kobo"], b["creator_side"]),
                                     unmatched)["win"] if unmatched else 0,
            "is_mine": bool(user and b["creator_id"] == user["id"])}


@router.post("/bets", status_code=201)
def create_bet(body: BetIn, request: Request, user=Depends(current_user), conn=Depends(get_conn),
               now=Depends(utcnow)):
    idem = Idempotent(conn, user["id"], request)
    if (prior := idem.replay()) is not None:
        return prior
    m = load_match(conn, body.match_id)
    assert_open(m, now)
    result_bet = body.kind == MATCH_RESULT
    if result_bet and not (settings.paid_play_enabled and settings.result_bets_enabled):
        raise ApiError(403, "result_bets_unavailable", "Home/Away bets aren't open yet")
    if result_bet and not body.stake_kobo:
        raise ApiError(422, "stake_required", "Home/Away bets need a stake")
    if body.stake_kobo:
        require_paid_play(conn, user, now, body.stake_kobo, result_bet=result_bet)
        assert_not_scorer(conn, user["id"], m["id"])
        errors = validate_new_bet(body.kind, body.stake_kobo, body.side if result_bet else None,
                                  settings.result_bets_enabled)
        if errors:
            raise ApiError(422, "bad_bet", errors[0], errors)
    if result_bet:
        if body.side is None:
            raise ApiError(422, "side_required", "pick Home or Away")
    else:
        if body.fantasy_team_id is None:
            raise ApiError(422, "team_required", "choose one of your teams")
        _own_team(conn, user, body.fantasy_team_id, body.match_id)
    open_count = conn.execute("select count(*) as n from p2p_bets where creator_id = %s and match_id = %s "
                              "and status in ('open', 'partially_matched')", (user["id"], body.match_id)).fetchone()["n"]
    if open_count >= 10:
        raise ApiError(409, "too_many_open", "you already have 10 open challenges on this match")
    bet = conn.execute(
        """insert into p2p_bets (kind, match_id, creator_id, creator_side, creator_fantasy_team_id, stake_kobo,
                                 visibility, invite_token, created_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (body.kind, body.match_id, user["id"], body.side if result_bet else None,
         None if result_bet else body.fantasy_team_id, body.stake_kobo, body.visibility,
         secrets.token_urlsafe(9), now),
    ).fetchone()
    if body.stake_kobo:
        wallet.hold(conn, user["id"], body.stake_kobo, "bet", bet["id"], now=now)
    bet_event(conn, bet["id"], None, "open", f"user:{user['id']}")
    return idem.save({**bet, "invite_path": f"#/challenge/{bet['invite_token']}"})


@router.get("/matches/{match_id}/bets")
def board(match_id: UUID, user=Depends(optional_user), conn=Depends(get_conn)):
    load_match(conn, match_id)
    rows = conn.execute(
        """select b.*, u.team_name from p2p_bets b join users u on u.id = b.creator_id
           where b.match_id = %s and b.visibility = 'board' and b.status in ('open', 'partially_matched')
           order by b.created_at""",
        (match_id,)).fetchall()
    records = _records(conn, {r["creator_id"] for r in rows})
    return [_card(r, records, user) for r in rows]


@router.get("/bets/invite/{token}")
def invite(token: str, user=Depends(optional_user), conn=Depends(get_conn), now=Depends(utcnow)):
    b = conn.execute("""select b.*, u.team_name from p2p_bets b join users u on u.id = b.creator_id
                        where b.invite_token = %s""", (token,)).fetchone()
    if b is None:
        raise ApiError(404, "challenge_not_found", "this challenge link isn't valid")
    m = load_match(conn, b["match_id"])
    return {**_card(b, _records(conn, {b["creator_id"]}), user),
            "match": {"id": m["id"], "home_team": m["home_team"], "away_team": m["away_team"],
                      "scheduled_start": m["scheduled_start"], "locked": is_locked(m, now)}}


@router.post("/bets/{bet_id}/fills", status_code=201)
def accept(bet_id: UUID, body: FillIn, request: Request, user=Depends(current_user), conn=Depends(get_conn),
           now=Depends(utcnow)):
    idem = Idempotent(conn, user["id"], request)
    if (prior := idem.replay()) is not None:
        return prior
    b = conn.execute("select * from p2p_bets where id = %s for update", (bet_id,)).fetchone()
    if b is None:
        raise ApiError(404, "challenge_not_found", "challenge not found")
    m = load_match(conn, b["match_id"])
    assert_open(m, now)
    if b["status"] not in OPEN_FOR_FILLS:
        raise ApiError(409, "challenge_unavailable", "this challenge has already been taken or closed")
    bet = _bet_model(conn, b)
    result_bet = b["kind"] == MATCH_RESULT
    amount = (body.amount_kobo or bet.unmatched) if result_bet else b["stake_kobo"]
    if b["stake_kobo"]:
        require_paid_play(conn, user, now, amount, result_bet=result_bet)
        assert_not_scorer(conn, user["id"], m["id"])
    errors = validate_fill(bet, str(user["id"]), amount, linked_users(conn, b["creator_id"]) if b["stake_kobo"] else frozenset())
    if errors:
        raise ApiError(409, "cannot_accept", errors[0], errors)
    team_id = None
    if not result_bet:
        if body.fantasy_team_id is None:
            raise ApiError(422, "team_required", "choose one of your teams")
        _own_team(conn, user, body.fantasy_team_id, b["match_id"])
        team_id = body.fantasy_team_id
    fill = conn.execute(
        """insert into p2p_bet_fills (bet_id, challenger_id, side, challenger_fantasy_team_id, amount_kobo, created_at)
           values (%s, %s, %s, %s, %s, %s) returning *""",
        (bet_id, user["id"], opposite(b["creator_side"]) if result_bet else None, team_id, amount, now)).fetchone()
    if b["stake_kobo"]:
        wallet.hold(conn, user["id"], amount, "bet_fill", fill["id"], now=now)
    matched = b["matched_kobo"] + amount
    status = "matched" if matched == b["stake_kobo"] else "partially_matched"
    conn.execute("update p2p_bets set status = %s, matched_kobo = %s where id = %s", (status, matched, bet_id))
    bet_event(conn, bet_id, b["status"], status, f"user:{user['id']}")
    return idem.save({"bet_id": bet_id, "status": status, "fill_id": fill["id"], "amount_kobo": amount,
                      "quote": quote_fill(bet, amount) if result_bet or b["stake_kobo"] else None})


@router.post("/bets/{bet_id}/cancel")
def cancel(bet_id: UUID, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    b = conn.execute("select * from p2p_bets where id = %s and creator_id = %s for update",
                     (bet_id, user["id"])).fetchone()
    if b is None:
        raise ApiError(404, "challenge_not_found", "challenge not found")
    if b["status"] != "open":
        raise ApiError(409, "cannot_cancel", "only an open challenge nobody has accepted can be withdrawn")
    h = wallet.open_hold(conn, "bet", bet_id)
    if h:
        wallet.release(conn, h, now, "refund")
    conn.execute("update p2p_bets set status = 'cancelled' where id = %s", (bet_id,))
    bet_event(conn, bet_id, "open", "cancelled", f"user:{user['id']}", "withdrawn by creator")
    return {"bet_id": bet_id, "status": "cancelled"}


@router.get("/me/bets")
def my_bets(user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    rows = conn.execute(
        """select b.*, f.challenger_id, f.challenger_fantasy_team_id, f.payout_kobo as fill_payout,
                  cu.team_name as creator_name, tu.team_name as taker_name,
                  ct.label as creator_label, tt.label as taker_label
           from p2p_bets b
           left join p2p_bet_fills f on f.bet_id = b.id
           join users cu on cu.id = b.creator_id
           left join users tu on tu.id = f.challenger_id
           left join fantasy_teams ct on ct.id = b.creator_fantasy_team_id
           left join fantasy_teams tt on tt.id = f.challenger_fantasy_team_id
           where b.creator_id = %(u)s or f.challenger_id = %(u)s
           order by b.created_at desc""", {"u": user["id"]}).fetchall()
    live = {}
    out = []
    for b in rows:
        m = load_match(conn, b["match_id"])
        me_creator = b["creator_id"] == user["id"]
        item = {"id": b["id"], "kind": b["kind"], "side": b["creator_side"] if me_creator else (
                    opposite(b["creator_side"]) if b["creator_side"] else None),
                "status": b["status"], "stake_kobo": b["stake_kobo"], "visibility": b["visibility"],
                "payout_kobo": b["creator_payout_kobo"] if me_creator else b["fill_payout"],
                "paid_out": b["paid_out_at"] is not None,
                "invite_path": f"#/challenge/{b['invite_token']}",
                "match": {"id": m["id"], "home_team": m["home_team"], "away_team": m["away_team"],
                          "scheduled_start": m["scheduled_start"], "status": m["status"]},
                "my_side": "creator" if me_creator else "taker",
                "my_team": b["creator_label"] if me_creator else b["taker_label"],
                "opponent": b["taker_name"] if me_creator else b["creator_name"],
                "my_points": None, "opponent_points": None, "result": None}
        if b["status"] == "settled" and b["kind"] == MATCH_RESULT:
            item.update(result="refunded" if b["outcome"] == "tie" else (
                "won" if (b["outcome"] == "creator") == me_creator else "lost"))
        elif b["status"] == "settled":
            mine, theirs = ((b["creator_points"], b["taker_points"]) if me_creator
                            else (b["taker_points"], b["creator_points"]))
            item.update(my_points=mine, opponent_points=theirs,
                        result="tie" if b["outcome"] == "tie" else ("won" if b["outcome"] == item["my_side"] else "lost"))
        elif b["kind"] == FANTASY_H2H and b["status"] == "matched" and is_locked(m, now) and m["status"] in ("live", "final_pending"):
            if m["id"] not in live:
                live[m["id"]] = stream_scores(conn, m, official_or_primary_scorer(conn, m), now)
            totals = team_totals(conn, live[m["id"]],
                                 [b["creator_fantasy_team_id"], b["challenger_fantasy_team_id"]])
            c, t = totals[b["creator_fantasy_team_id"]], totals[b["challenger_fantasy_team_id"]]
            item.update(my_points=c if me_creator else t, opponent_points=t if me_creator else c)
        out.append(item)
    return out
