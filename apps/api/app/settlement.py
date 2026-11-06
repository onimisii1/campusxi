"""Closing out a match's contests and challenges (PRD 6.10, 6.11).

Runs inside the admin's confirm/abandon transaction. Free contests and challenges just get ranks
and results. Paid ones also capture the held money into a pot and book each prize; the cash is
paid out by release_payouts once the dispute hold has passed. Abandoned and walkover matches
release every hold, so everyone gets their money (and coins) back.
"""
from datetime import timedelta

from app import wallet
from app.config import settings
from app.engines.p2p import FANTASY_H2H, Bet, Fill, commission, settle_h2h, settle_result_bet
from app.engines.payouts import final_ranks, payout_table, settle_contest
from app.fantasy import team_totals
from app.live import stream_scores


def bet_event(conn, bet_id, from_status, to_status, actor: str, reason: str | None = None):
    conn.execute("insert into p2p_bet_events (bet_id, from_status, to_status, actor, reason) "
                 "values (%s, %s, %s, %s, %s)", (bet_id, from_status, to_status, actor, reason))


def settle_free(conn, match: dict, official_scorer_id, now):
    scores = stream_scores(conn, {**match, "status": "confirmed"}, official_scorer_id)

    from app.routers.contests import ENTRIES_SQL, entry_points

    for contest in conn.execute("select id from contests where match_id = %s and entry_fee_kobo = 0 "
                                "and status in ('open', 'locked')", (match["id"],)).fetchall():
        entries = conn.execute(ENTRIES_SQL, (contest["id"],)).fetchall()
        points = entry_points(conn, match, official_scorer_id, scores, entries)  # late joiners: since joining
        scored = [(e["id"], points[e["id"]]) for e in entries]
        ranks = final_ranks(scored)
        for entry_id, pts in scored:
            conn.execute("update contest_entries set final_points = %s, final_rank = %s where id = %s",
                         (pts, ranks[entry_id], entry_id))
        conn.execute("update contests set status = 'settled' where id = %s", (contest["id"],))

    bets = conn.execute(
        """select b.id, b.status, b.creator_fantasy_team_id, f.challenger_fantasy_team_id
           from p2p_bets b left join p2p_bet_fills f on f.bet_id = b.id
           where b.match_id = %s and b.kind = 'fantasy_h2h' and b.stake_kobo = 0
             and b.status in ('open', 'matched')""", (match["id"],)).fetchall()
    team_ids = {t for b in bets for t in (b["creator_fantasy_team_id"], b["challenger_fantasy_team_id"]) if t}
    totals = team_totals(conn, scores, team_ids)
    for b in bets:
        if b["status"] == "open":
            conn.execute("update p2p_bets set status = 'cancelled' where id = %s", (b["id"],))
            bet_event(conn, b["id"], "open", "cancelled", "system:settle", "no one accepted before kick-off")
            continue
        mine, theirs = totals[b["creator_fantasy_team_id"]], totals[b["challenger_fantasy_team_id"]]
        outcome = "tie" if mine == theirs else ("creator" if mine > theirs else "taker")
        conn.execute("""update p2p_bets set status = 'settled', creator_points = %s, taker_points = %s,
                        outcome = %s, settled_at = %s where id = %s""", (mine, theirs, outcome, now, b["id"]))
        bet_event(conn, b["id"], "matched", "settled", "system:settle", outcome)

    result = conn.execute("select winner from match_results where match_id = %s", (match["id"],)).fetchone()
    settle_paid_contests(conn, match, official_scorer_id, scores, now)
    settle_paid_bets(conn, match, scores, result["winner"] if result else None, now)


def _payout_after(now):
    return now + timedelta(hours=settings.payout_hold_hours)


def refund_contest(conn, contest_id, now, reason: str) -> None:
    for e in conn.execute("select id from contest_entries where contest_id = %s", (contest_id,)).fetchall():
        h = wallet.open_hold(conn, "contest_entry", e["id"])
        if h:
            wallet.release(conn, h, now, "refund")
    conn.execute("update contests set status = 'cancelled' where id = %s", (contest_id,))


def settle_paid_contests(conn, match, official_scorer_id, scores, now) -> None:
    from app.routers.contests import ENTRIES_SQL, entry_points

    for c in conn.execute("select * from contests where match_id = %s and entry_fee_kobo > 0 "
                          "and status in ('open', 'locked') for update", (match["id"],)).fetchall():
        entries = conn.execute(ENTRIES_SQL, (c["id"],)).fetchall()
        if len(entries) < c["min_fill"]:
            refund_contest(conn, c["id"], now, "not enough entries")
            continue
        points = entry_points(conn, match, official_scorer_id, scores, entries)
        scored = [(e["id"], points[e["id"]]) for e in entries]          # join order breaks kobo splits
        gross = sum(e["fee_kobo"] for e in entries)
        table = payout_table(len(entries), c["entry_fee_kobo"], c["rake_bps"], c["first_share_bps"], gross)
        prizes = settle_contest(scored, table)
        ranks = final_ranks(scored)
        pot = wallet.pot("contest", c["id"])
        for e in entries:
            wallet.capture(conn, wallet.open_hold(conn, "contest_entry", e["id"]), pot, "entry_fee", now)
            conn.execute("update contest_entries set final_points = %s, final_rank = %s, prize_kobo = %s where id = %s",
                         (points[e["id"]], ranks[e["id"]], prizes.get(e["id"], 0), e["id"]))
        conn.execute("update contests set status = 'settled', fee_kobo = %s, payout_after = %s where id = %s",
                     (gross - sum(prizes.values()), _payout_after(now), c["id"]))


def _bet(conn, b):
    fills = conn.execute("select * from p2p_bet_fills where bet_id = %s order by created_at, id", (b["id"],)).fetchall()
    model = Bet(b["kind"], str(b["creator_id"]), b["stake_kobo"], b["creator_side"],
                tuple(Fill(str(f["challenger_id"]), f["amount_kobo"]) for f in fills), b["commission_bps"])
    return model, fills


def refund_bet(conn, b, now, status: str, reason: str) -> None:
    _, fills = _bet(conn, b)
    for ref_type, ref_id in [("bet", b["id"])] + [("bet_fill", f["id"]) for f in fills]:
        h = wallet.open_hold(conn, ref_type, ref_id)
        if h:
            wallet.release(conn, h, now, "refund")
    conn.execute("update p2p_bets set status = %s where id = %s", (status, b["id"]))
    bet_event(conn, b["id"], b["status"], status, "system:settle", reason)


def settle_paid_bets(conn, match, scores, winner, now) -> None:
    for b in conn.execute("""select * from p2p_bets where match_id = %s and stake_kobo > 0
                             and status in ('open', 'partially_matched', 'matched') for update""",
                          (match["id"],)).fetchall():
        model, fills = _bet(conn, b)
        if not fills:
            refund_bet(conn, b, now, "refunded", "no one accepted before kick-off")
            continue
        if b["kind"] == FANTASY_H2H:
            totals = team_totals(conn, scores, [b["creator_fantasy_team_id"], fills[0]["challenger_fantasy_team_id"]])
            mine, theirs = totals[b["creator_fantasy_team_id"]], totals[fills[0]["challenger_fantasy_team_id"]]
            s = settle_h2h(model, mine, theirs)
            outcome = "tie" if mine == theirs else ("creator" if mine > theirs else "taker")
            points = (mine, theirs)
        else:
            s = settle_result_bet(model, winner)
            outcome = "tie" if winner == "draw" else ("creator" if winner == b["creator_side"] else "taker")
            points = (None, None)
        pot = wallet.pot("bet", b["id"])
        for ref_type, ref_id in [("bet", b["id"])] + [("bet_fill", f["id"]) for f in fills]:
            wallet.capture(conn, wallet.open_hold(conn, ref_type, ref_id), pot, "stake", now)
        for f, paid in zip(fills, s.fills):
            fee = commission(f["amount_kobo"], b["commission_bps"]) if paid > f["amount_kobo"] else 0
            conn.execute("update p2p_bet_fills set payout_kobo = %s, commission_kobo = %s where id = %s",
                         (paid, fee, f["id"]))
        conn.execute("""update p2p_bets set status = 'settled', outcome = %s, creator_points = %s, taker_points = %s,
                        settled_at = %s, creator_payout_kobo = %s, platform_kobo = %s, payout_after = %s
                        where id = %s""",
                     (outcome, *points, now, s.creator, s.platform, _payout_after(now), b["id"]))
        bet_event(conn, b["id"], b["status"], "settled", "system:settle", outcome)


def release_payouts(conn, now) -> dict:
    """Pay out prizes and winnings whose dispute hold has passed (always cash)."""
    done = {"contests": 0, "bets": 0}
    for c in conn.execute("""select * from contests where status = 'settled' and entry_fee_kobo > 0
                             and paid_out_at is null and payout_after <= %s for update""", (now,)).fetchall():
        prizes = {}
        for e in conn.execute("select user_id, prize_kobo from contest_entries where contest_id = %s and prize_kobo > 0",
                              (c["id"],)).fetchall():
            prizes[e["user_id"]] = prizes.get(e["user_id"], 0) + e["prize_kobo"]
        wallet.pay_out(conn, wallet.pot("contest", c["id"]), prizes, c["fee_kobo"], "contest", c["id"])
        conn.execute("update contest_entries set prize_paid_at = %s where contest_id = %s and prize_kobo > 0",
                     (now, c["id"]))
        conn.execute("update contests set paid_out_at = %s where id = %s", (now, c["id"]))
        done["contests"] += 1
    for b in conn.execute("""select * from p2p_bets where status = 'settled' and stake_kobo > 0
                             and paid_out_at is null and payout_after <= %s for update""", (now,)).fetchall():
        prizes = {b["creator_id"]: b["creator_payout_kobo"]}
        for f in conn.execute("select challenger_id, payout_kobo from p2p_bet_fills where bet_id = %s",
                              (b["id"],)).fetchall():
            prizes[f["challenger_id"]] = prizes.get(f["challenger_id"], 0) + f["payout_kobo"]
        wallet.pay_out(conn, wallet.pot("bet", b["id"]), prizes, b["platform_kobo"], "bet", b["id"],
                       prize_type="payout", fee_type="commission")
        conn.execute("update p2p_bets set paid_out_at = %s where id = %s", (now, b["id"]))
        done["bets"] += 1
    return done


def refund_at_lock(conn, now) -> dict:
    """At kick-off: paid contests short of their minimum and paid challenges nobody accepted are refunded."""
    from app.matches import MATCH_SQL, is_locked
    done = {"contests": 0, "bets": 0}
    for c in conn.execute(
            """select c.*, (select count(*) from contest_entries e where e.contest_id = c.id) as n from contests c
               join matches m on m.id = c.match_id where c.entry_fee_kobo > 0 and c.status = 'open'
               and m.scheduled_start <= %s""", (now,)).fetchall():
        m = conn.execute(MATCH_SQL + " where m.id = %s", (c["match_id"],)).fetchone()
        if is_locked(m, now) and c["n"] < c["min_fill"]:
            refund_contest(conn, c["id"], now, "not enough entries")
            done["contests"] += 1
    for b in conn.execute(
            """select b.* from p2p_bets b join matches m on m.id = b.match_id where b.stake_kobo > 0
               and b.status = 'open' and m.scheduled_start <= %s for update of b""", (now,)).fetchall():
        refund_bet(conn, b, now, "refunded", "no one accepted before kick-off")
        done["bets"] += 1
    return done


def void_match(conn, match_id, now=None):
    """Abandoned or walkover: nothing was played, so every entry fee and stake goes back."""
    for c in conn.execute("select id from contests where match_id = %s and status in ('open', 'locked')",
                          (match_id,)).fetchall():
        refund_contest(conn, c["id"], now, "match void")
    for b in conn.execute("select * from p2p_bets where match_id = %s and status in "
                          "('open', 'partially_matched', 'matched', 'locked')", (match_id,)).fetchall():
        refund_bet(conn, b, now, "void", "match void")
