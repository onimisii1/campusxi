"""P2P challenges (PRD 5.8, 8.5). Phase 4: free fantasy H2H "bragging rights" challenges only.

A challenge is posted to the match's open board or shared as a link. The creator's
team stays hidden until kick-off so nobody can copy it. Paid stakes and Home/Away
result bets arrive with paid play.
"""
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import current_user, optional_user
from app.clock import utcnow
from app.db import get_conn
from app.engines.p2p import FANTASY_H2H, Bet, Fill, validate_fill
from app.errors import ApiError
from app.fantasy import team_totals
from app.live import official_or_primary_scorer, stream_scores
from app.matches import assert_open, is_locked, load_match
from app.settlement import bet_event

router = APIRouter(tags=["challenges"])


class BetIn(BaseModel):
    kind: Literal["fantasy_h2h", "match_result"] = "fantasy_h2h"
    match_id: UUID
    fantasy_team_id: UUID
    stake_kobo: int = Field(default=0, ge=0)
    visibility: Literal["board", "direct"] = "board"


class FillIn(BaseModel):
    fantasy_team_id: UUID


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
    return {"id": b["id"], "kind": b["kind"], "match_id": b["match_id"], "stake_kobo": b["stake_kobo"],
            "visibility": b["visibility"], "status": b["status"], "created_at": b["created_at"],
            "creator": {"team_name": b["team_name"], "record": records.get(b["creator_id"])},
            "is_mine": bool(user and b["creator_id"] == user["id"])}


@router.post("/bets", status_code=201)
def create_bet(body: BetIn, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    if body.kind != FANTASY_H2H:
        raise ApiError(403, "result_bets_unavailable", "Home/Away bets are not available")
    if body.stake_kobo:
        raise ApiError(403, "paid_play_unavailable", "paid challenges open once CampusXI is licensed")
    m = load_match(conn, body.match_id)
    assert_open(m, now)
    _own_team(conn, user, body.fantasy_team_id, body.match_id)
    open_count = conn.execute("select count(*) as n from p2p_bets where creator_id = %s and match_id = %s "
                              "and status = 'open'", (user["id"], body.match_id)).fetchone()["n"]
    if open_count >= 10:
        raise ApiError(409, "too_many_open", "you already have 10 open challenges on this match")
    bet = conn.execute(
        """insert into p2p_bets (kind, match_id, creator_id, creator_fantasy_team_id, stake_kobo, visibility,
                                 invite_token)
           values ('fantasy_h2h', %s, %s, %s, 0, %s, %s) returning *""",
        (body.match_id, user["id"], body.fantasy_team_id, body.visibility, secrets.token_urlsafe(9)),
    ).fetchone()
    bet_event(conn, bet["id"], None, "open", f"user:{user['id']}")
    return {**bet, "invite_path": f"#/challenge/{bet['invite_token']}"}


@router.get("/matches/{match_id}/bets")
def board(match_id: UUID, user=Depends(optional_user), conn=Depends(get_conn)):
    load_match(conn, match_id)
    rows = conn.execute(
        """select b.*, u.team_name from p2p_bets b join users u on u.id = b.creator_id
           where b.match_id = %s and b.visibility = 'board' and b.status = 'open' order by b.created_at""",
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
def accept(bet_id: UUID, body: FillIn, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    b = conn.execute("select * from p2p_bets where id = %s for update", (bet_id,)).fetchone()
    if b is None:
        raise ApiError(404, "challenge_not_found", "challenge not found")
    m = load_match(conn, b["match_id"])
    assert_open(m, now)
    if b["status"] != "open":
        raise ApiError(409, "challenge_unavailable", "this challenge has already been taken or closed")
    fills = tuple(Fill(str(f["challenger_id"]), f["amount_kobo"]) for f in conn.execute(
        "select challenger_id, amount_kobo from p2p_bet_fills where bet_id = %s", (bet_id,)).fetchall())
    errors = validate_fill(Bet(b["kind"], str(b["creator_id"]), b["stake_kobo"], None, fills),
                           str(user["id"]), b["stake_kobo"])
    if errors:
        raise ApiError(409, "cannot_accept", errors[0])
    _own_team(conn, user, body.fantasy_team_id, b["match_id"])
    conn.execute("""insert into p2p_bet_fills (bet_id, challenger_id, challenger_fantasy_team_id, amount_kobo)
                    values (%s, %s, %s, %s)""", (bet_id, user["id"], body.fantasy_team_id, b["stake_kobo"]))
    conn.execute("update p2p_bets set status = 'matched', matched_kobo = stake_kobo where id = %s", (bet_id,))
    bet_event(conn, bet_id, "open", "matched", f"user:{user['id']}")
    return {"bet_id": bet_id, "status": "matched"}


@router.post("/bets/{bet_id}/cancel")
def cancel(bet_id: UUID, user=Depends(current_user), conn=Depends(get_conn)):
    b = conn.execute("select * from p2p_bets where id = %s and creator_id = %s for update",
                     (bet_id, user["id"])).fetchone()
    if b is None:
        raise ApiError(404, "challenge_not_found", "challenge not found")
    if b["status"] != "open":
        raise ApiError(409, "cannot_cancel", "only an open challenge nobody has accepted can be withdrawn")
    conn.execute("update p2p_bets set status = 'cancelled' where id = %s", (bet_id,))
    bet_event(conn, bet_id, "open", "cancelled", f"user:{user['id']}", "withdrawn by creator")
    return {"bet_id": bet_id, "status": "cancelled"}


@router.get("/me/bets")
def my_bets(user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    rows = conn.execute(
        """select b.*, f.challenger_id, f.challenger_fantasy_team_id,
                  cu.team_name as creator_name, tu.team_name as taker_name,
                  ct.label as creator_label, tt.label as taker_label
           from p2p_bets b
           left join p2p_bet_fills f on f.bet_id = b.id
           join users cu on cu.id = b.creator_id
           left join users tu on tu.id = f.challenger_id
           join fantasy_teams ct on ct.id = b.creator_fantasy_team_id
           left join fantasy_teams tt on tt.id = f.challenger_fantasy_team_id
           where b.creator_id = %(u)s or f.challenger_id = %(u)s
           order by b.created_at desc""", {"u": user["id"]}).fetchall()
    live = {}
    out = []
    for b in rows:
        m = load_match(conn, b["match_id"])
        me_creator = b["creator_id"] == user["id"]
        item = {"id": b["id"], "status": b["status"], "stake_kobo": b["stake_kobo"], "visibility": b["visibility"],
                "invite_path": f"#/challenge/{b['invite_token']}",
                "match": {"id": m["id"], "home_team": m["home_team"], "away_team": m["away_team"],
                          "scheduled_start": m["scheduled_start"], "status": m["status"]},
                "my_side": "creator" if me_creator else "taker",
                "my_team": b["creator_label"] if me_creator else b["taker_label"],
                "opponent": b["taker_name"] if me_creator else b["creator_name"],
                "my_points": None, "opponent_points": None, "result": None}
        if b["status"] == "settled":
            mine, theirs = ((b["creator_points"], b["taker_points"]) if me_creator
                            else (b["taker_points"], b["creator_points"]))
            item.update(my_points=mine, opponent_points=theirs,
                        result="tie" if b["outcome"] == "tie" else ("won" if b["outcome"] == item["my_side"] else "lost"))
        elif b["status"] == "matched" and is_locked(m, now) and m["status"] in ("live", "final_pending"):
            if m["id"] not in live:
                live[m["id"]] = stream_scores(conn, m, official_or_primary_scorer(conn, m), now)
            totals = team_totals(conn, live[m["id"]],
                                 [b["creator_fantasy_team_id"], b["challenger_fantasy_team_id"]])
            c, t = totals[b["creator_fantasy_team_id"]], totals[b["challenger_fantasy_team_id"]]
            item.update(my_points=c if me_creator else t, opponent_points=t if me_creator else c)
        out.append(item)
    return out
