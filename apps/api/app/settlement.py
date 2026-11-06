"""Closing out a match's free contests and challenges (PRD 6.10, 6.11).

Runs inside the admin's confirm/abandon transaction. Paid contests and stakes are
settled with the wallet in Phase 5, so only zero-fee contests and zero-stake
challenges are touched here.
"""
from app.engines.payouts import final_ranks
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


def void_match(conn, match_id):
    conn.execute("update contests set status = 'cancelled' where match_id = %s and status in ('open', 'locked')",
                 (match_id,))
    for b in conn.execute("select id, status from p2p_bets where match_id = %s and status in "
                          "('open', 'partially_matched', 'matched', 'locked')", (match_id,)).fetchall():
        conn.execute("update p2p_bets set status = 'void' where id = %s", (b["id"],))
        bet_event(conn, b["id"], b["status"], "void", "system:abandon", "match abandoned")
