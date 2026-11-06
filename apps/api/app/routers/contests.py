"""Contests (PRD 5.4, 8.4) and leaderboards (PRD F3). Paid entries hold the fee in the wallet
until settlement (app/settlement.py); prizes are paid after the dispute hold (app/jobs.py)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.audit import audit
from app.auth import current_user, optional_user, require_admin
from app.clock import utcnow
from app.config import settings
from app.db import get_conn
from app import wallet
from app.engines.payouts import final_ranks, min_fill, payout_table, validate_contest
from app.gate import require_paid_play
from app.idempotency import Idempotent
from app.errors import ApiError
from app.fantasy import late_watermark, totals_since
from app.live import official_or_primary_scorer, stream_scores
from app.matches import assert_open, assert_open_or_late, is_locked, late_fee, late_window, load_match

router = APIRouter(tags=["contests"])

SCORED_STATUSES = ("live", "final_pending", "confirmed")


class ContestIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    capacity: int = Field(ge=2, le=1000)
    team_cap: int = Field(default=10, ge=1, le=10)
    prize_text: str | None = Field(default=None, max_length=200)
    entry_fee_kobo: int = Field(default=0, ge=0)


class EntryIn(BaseModel):
    fantasy_team_id: UUID


ENTRIES_SQL = """
    select e.id, e.fantasy_team_id, e.user_id, e.final_points, e.final_rank, e.fee_kobo,
           e.late_after_event_id, e.late_elapsed_minutes,
           t.label, t.late_after_event_id as team_after, t.late_elapsed_minutes as team_elapsed, u.team_name
    from contest_entries e join fantasy_teams t on t.id = e.fantasy_team_id
    join users u on u.id = e.user_id where e.contest_id = %s order by e.joined_at, e.id
"""


def entry_points(conn, match, scorer_id, scores, entries) -> dict:
    """{entry_id: points}; late entries (or late-built teams) only count points after joining."""
    return totals_since(conn, match, scorer_id, scores, [
        (e["id"], e["fantasy_team_id"],
         *late_watermark((e["late_after_event_id"], e["late_elapsed_minutes"]), (e["team_after"], e["team_elapsed"])))
        for e in entries])


def create_free_contest(conn, match_id, name="Free contest", capacity=None, team_cap=10, prize_text=None):
    capacity = capacity or settings.default_free_contest_capacity
    return conn.execute(
        """insert into contests (match_id, name, capacity, entry_fee_kobo, min_fill, team_cap, prize_text)
           values (%s, %s, %s, 0, 2, %s, %s) returning *""",
        (match_id, name, capacity, team_cap, prize_text),
    ).fetchone()


MINI_FEE = 40_000          # the N400 Mini ticket
MIN_STANDARD_FEE = 100_000  # standard contests start at N1,000


def _no_paid_play():
    raise ApiError(403, "paid_play_unavailable", "paid contests aren't open yet")


def assert_not_scorer(conn, user_id, match_id):
    """Scorers control the data, so they can't put money on the matches they score."""
    if conn.execute("select 1 from match_scorers where match_id = %s and user_id = %s", (match_id, user_id)).fetchone():
        raise ApiError(403, "scorer_conflict", "you're scoring this match, so you can't play it for money")


def create_paid_contest(conn, match_id, name, capacity, fee, team_cap=10, prize_text=None):
    if fee != MINI_FEE and fee < MIN_STANDARD_FEE:
        raise ApiError(422, "bad_fee", "entry is ₦400 (Mini) or from ₦1,000")
    errors = validate_contest(capacity, fee)
    if errors:
        raise ApiError(422, "unfundable", errors[0], errors)
    return conn.execute(
        """insert into contests (match_id, name, capacity, entry_fee_kobo, min_fill, team_cap, prize_text, is_mini)
           values (%s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (match_id, name, capacity, fee, max(2, min_fill(capacity)), team_cap, prize_text, fee == MINI_FEE),
    ).fetchone()


@router.post("/admin/matches/{match_id}/contests", status_code=201)
def add_contest(match_id: UUID, body: ContestIn, user=Depends(require_admin), conn=Depends(get_conn),
                now=Depends(utcnow)):
    m = load_match(conn, match_id, published_only=False)
    if "superadmin" not in user["roles"] and user["school_id"] != m["school_id"]:
        raise ApiError(403, "other_school", "you can only manage your own school")
    assert_open(m, now)
    if body.entry_fee_kobo:
        if not settings.paid_play_enabled:
            _no_paid_play()
        c = create_paid_contest(conn, match_id, body.name, body.capacity, body.entry_fee_kobo, body.team_cap,
                                body.prize_text)
    else:
        c = create_free_contest(conn, match_id, body.name, body.capacity, body.team_cap, body.prize_text)
    audit(conn, user["id"], "contest.create", "contest", c["id"], name=c["name"], capacity=c["capacity"],
          entry_fee_kobo=c["entry_fee_kobo"])
    return c


@router.get("/matches/{match_id}/contests")
def list_contests(match_id: UUID, user=Depends(optional_user), conn=Depends(get_conn), now=Depends(utcnow)):
    m = load_match(conn, match_id)
    rows = conn.execute(
        """select c.*, (select count(*) from contest_entries e where e.contest_id = c.id) as entries
           from contests c where c.match_id = %s order by c.entry_fee_kobo, c.created_at""", (match_id,)).fetchall()
    mine = {}
    if user:
        for e in conn.execute(
                """select e.id, e.contest_id, e.fantasy_team_id, t.label, e.final_rank, e.final_points
                   from contest_entries e join fantasy_teams t on t.id = e.fantasy_team_id
                   join contests c on c.id = e.contest_id
                   where c.match_id = %s and e.user_id = %s order by t.label""", (match_id, user["id"])).fetchall():
            mine.setdefault(e["contest_id"], []).append(
                {"entry_id": e["id"], "fantasy_team_id": e["fantasy_team_id"], "label": e["label"],
                 "final_rank": e["final_rank"], "final_points": e["final_points"]})
    locked = is_locked(m, now)
    late = late_window(conn, m, now)
    return [{
        "id": c["id"], "name": c["name"], "prize_text": c["prize_text"], "entry_fee_kobo": c["entry_fee_kobo"],
        "capacity": c["capacity"], "entries": c["entries"], "spots_left": c["capacity"] - c["entries"],
        "team_cap": c["team_cap"], "status": c["status"], "locked": locked, "min_entries": c["min_fill"],
        "is_mini": c["is_mini"],
        "late_join": None if late is None or c["status"] != "open" else {
            "until_minute": late["until_minute"], "minute": late["minute"],
            "entry_fee_kobo": late_fee(c["entry_fee_kobo"])},
        "my_entries": mine.get(c["id"], []),
    } for c in rows]


def _ranges(prizes) -> list:
    """[prize per rank] -> [{'from', 'to', 'prize_kobo'}] with equal neighbours merged."""
    out = []
    for i, p in enumerate(prizes, start=1):
        if out and out[-1]["prize_kobo"] == p:
            out[-1]["to"] = i
        else:
            out.append({"from": i, "to": i, "prize_kobo": p})
    return out


@router.get("/contests/{contest_id}/payout-preview")
def payout_preview(contest_id: UUID, conn=Depends(get_conn)):
    """Winnings tab (PRD 8.4): prize table if the contest fills, and as it stands now."""
    c = conn.execute(
        """select c.*, (select count(*) from contest_entries e where e.contest_id = c.id) as entries,
                  (select coalesce(sum(fee_kobo), 0)::bigint from contest_entries e where e.contest_id = c.id) as fees
           from contests c where c.id = %s""", (contest_id,)).fetchone()
    if c is None:
        raise ApiError(404, "contest_not_found", "contest not found")
    base = {"contest_id": contest_id, "free": c["entry_fee_kobo"] == 0, "prize_text": c["prize_text"],
            "entry_fee_kobo": c["entry_fee_kobo"], "rake_bps": c["rake_bps"], "min_entries": c["min_fill"],
            "max_entries": c["capacity"], "entries": c["entries"], "maximum": None, "current": None}
    if base["free"]:
        return base

    def table(n, gross=None):
        t = payout_table(n, c["entry_fee_kobo"], c["rake_bps"], c["first_share_bps"], gross)
        return {"entries": n, "pool_kobo": t.pool, "ranks_paid": t.paid, "rows": _ranges(t.prizes)}

    base["maximum"] = table(c["capacity"])
    if c["entries"] >= 2:
        base["current"] = table(c["entries"], max(c["fees"], c["entries"] * c["entry_fee_kobo"]))
    return base


@router.post("/contests/{contest_id}/entries", status_code=201)
def join_contest(contest_id: UUID, body: EntryIn, request: Request, user=Depends(current_user),
                 conn=Depends(get_conn), now=Depends(utcnow)):
    idem = Idempotent(conn, user["id"], request)
    if (prior := idem.replay()) is not None:
        return prior
    contest = conn.execute("select * from contests where id = %s for update", (contest_id,)).fetchone()
    if contest is None:
        raise ApiError(404, "contest_not_found", "contest not found")
    m = load_match(conn, contest["match_id"])
    conn.execute("select id from matches where id = %s for update", (m["id"],))  # freeze the watermark
    late = assert_open_or_late(conn, m, now)
    if contest["status"] != "open":
        raise ApiError(409, "contest_closed", "this contest is closed")
    fee = late_fee(contest["entry_fee_kobo"]) if late else contest["entry_fee_kobo"]
    if fee:
        require_paid_play(conn, user, now, fee)
        assert_not_scorer(conn, user["id"], m["id"])
    team = conn.execute("select * from fantasy_teams where id = %s and user_id = %s",
                        (body.fantasy_team_id, user["id"])).fetchone()
    if team is None or team["match_id"] != contest["match_id"]:
        raise ApiError(422, "wrong_team", "enter with one of your teams for this match")
    counts = conn.execute(
        "select count(*) as total, count(*) filter (where user_id = %s) as mine from contest_entries "
        "where contest_id = %s", (user["id"], contest_id)).fetchone()
    if counts["total"] >= contest["capacity"]:
        raise ApiError(409, "contest_full", "this contest is full")
    if counts["mine"] >= contest["team_cap"]:
        raise ApiError(409, "team_cap", f"you can enter at most {contest['team_cap']} teams in this contest")
    entry = conn.execute(
        """insert into contest_entries (contest_id, fantasy_team_id, user_id, fee_kobo,
                                        late_after_event_id, late_elapsed_minutes)
           values (%s, %s, %s, %s, %s, %s)
           on conflict (contest_id, fantasy_team_id) do nothing returning *""",
        (contest_id, body.fantasy_team_id, user["id"], fee,
         late["after_event_id"] if late else None, late["minute"] if late else None),
    ).fetchone()
    if entry is None:
        raise ApiError(409, "already_entered", "that team is already in this contest")
    if fee:
        h = wallet.hold(conn, user["id"], fee, "contest_entry", entry["id"], now=now)
        entry = {**entry, "paid_cash_kobo": h["cash_kobo"], "paid_bonus_kobo": h["bonus_kobo"]}
    return idem.save(entry)


@router.delete("/entries/{entry_id}", status_code=204)
def leave_contest(entry_id: UUID, user=Depends(current_user), conn=Depends(get_conn), now=Depends(utcnow)):
    entry = conn.execute(
        """select e.*, c.match_id from contest_entries e join contests c on c.id = e.contest_id
           where e.id = %s and e.user_id = %s""", (entry_id, user["id"])).fetchone()
    if entry is None:
        raise ApiError(404, "entry_not_found", "entry not found")
    assert_open(load_match(conn, entry["match_id"]), now)
    h = wallet.open_hold(conn, "contest_entry", entry_id)
    if h:
        wallet.release(conn, h, now, "refund")
    conn.execute("delete from contest_entries where id = %s", (entry_id,))


@router.get("/contests/{contest_id}/leaderboard")
def contest_leaderboard(contest_id: UUID, user=Depends(optional_user), conn=Depends(get_conn),
                        now=Depends(utcnow)):
    contest = conn.execute("select * from contests where id = %s", (contest_id,)).fetchone()
    if contest is None:
        raise ApiError(404, "contest_not_found", "contest not found")
    m = load_match(conn, contest["match_id"])
    entries = conn.execute(ENTRIES_SQL, (contest_id,)).fetchall()
    if contest["status"] == "settled":
        scored = {e["id"]: e["final_points"] for e in entries}
        ranks = {e["id"]: e["final_rank"] for e in entries}
        source = "final"
    else:
        scores, scorer = {}, None
        if m["status"] in SCORED_STATUSES:
            scorer = official_or_primary_scorer(conn, m)
            scores = stream_scores(conn, m, scorer, now)
        scored = entry_points(conn, m, scorer, scores, entries)
        ranks = final_ranks(list(scored.items()))
        source = "live" if m["status"] in SCORED_STATUSES else "not_started"
    rows = [{"rank": ranks[e["id"]], "entry_id": e["id"], "team_name": e["team_name"], "label": e["label"],
             "points": scored[e["id"]], "is_me": bool(user and e["user_id"] == user["id"]),
             "joined_minute": late_watermark((e["late_after_event_id"], e["late_elapsed_minutes"]),
                                             (e["team_after"], e["team_elapsed"]))[1]} for e in entries]
    rows.sort(key=lambda r: (r["rank"], r["team_name"].lower(), r["label"]))
    return {"contest_id": contest_id, "match_id": contest["match_id"], "name": contest["name"],
            "status": contest["status"], "source": source,
            "match_status": m["status"], "entries": rows}
