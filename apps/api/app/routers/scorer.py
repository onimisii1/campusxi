"""Scorer app API (PRD 5.5, 8.7): assigned matches, offline-safe event batches, final submission.

Events are append-only. Each carries the scorer device's client_seq; resending the
same event is a harmless duplicate, so a phone that lost signal can simply retry.
Undo is a new event that reverses an earlier one.
"""
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.audit import audit
from app.auth import require_roles
from app.clock import utcnow
from app.db import get_conn
from app.engines.scoring.engine import FOOTBALL_TIMED_EVENTS, STRUCTURAL_EVENTS
from app.engines.scoring.rules import FOOTBALL, SCORING_RULES
from app.errors import ApiError
from app.live import lineup_entries
from app.matches import kick_off, load_match

router = APIRouter(prefix="/scorer", tags=["scorer"])
require_scorer = require_roles("scorer")

EARLY_START = timedelta(minutes=30)       # scorers may start recording 30 min before kick-off
SCORING_STATUSES = ("scheduled", "lineup_out", "live")


class EventIn(BaseModel):
    client_seq: int = Field(ge=1)
    athlete_id: UUID
    event_type: str
    minute: int | None = Field(default=None, ge=0, le=200)
    amount: int = Field(default=1, ge=1, le=3)
    reverses_client_seq: int | None = Field(default=None, ge=1)


class EventBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=200)


class SubmitIn(BaseModel):
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    shootout_winner: Literal["home", "away"] | None = None


def _assignment(conn, match_id, user) -> dict:
    row = conn.execute("select role from match_scorers where match_id = %s and user_id = %s",
                       (match_id, user["id"])).fetchone()
    if row is None:
        raise ApiError(403, "not_assigned", "you are not assigned to score this match")
    return row


def _event_types(match) -> set:
    rules = SCORING_RULES[match["rules_version"]]
    return set(rules.events) | set(rules.position_events) | STRUCTURAL_EVENTS


@router.get("/matches")
def my_matches(user=Depends(require_scorer), conn=Depends(get_conn)):
    return conn.execute(
        """select m.id, m.scheduled_start, m.status, m.venue, t.sport, t.name as tournament, s.role,
                  h.name as home_team, a.name as away_team,
                  exists (select 1 from stat_submissions x where x.match_id = m.id and x.scorer_id = %(u)s)
                    as submitted
           from match_scorers s
           join matches m on m.id = s.match_id
           join tournaments t on t.id = m.tournament_id
           join teams h on h.id = m.home_team_id
           join teams a on a.id = m.away_team_id
           where s.user_id = %(u)s and m.status not in ('confirmed', 'abandoned')
           order by m.scheduled_start""",
        {"u": user["id"]},
    ).fetchall()


@router.get("/matches/{match_id}")
def scorer_match(match_id: UUID, user=Depends(require_scorer), conn=Depends(get_conn)):
    match = load_match(conn, match_id, published_only=False)
    role = _assignment(conn, match_id, user)["role"]
    lineup = lineup_entries(conn, match)
    events = conn.execute(
        """select e.client_seq, e.athlete_id, e.event_type, e.minute, e.amount, r.client_seq as reverses_client_seq,
                  e.created_at
           from stat_events e left join stat_events r on r.id = e.reverses_event_id
           where e.match_id = %s and e.scorer_id = %s order by e.client_seq""",
        (match_id, user["id"]),
    ).fetchall()
    submission = conn.execute("select * from stat_submissions where match_id = %s and scorer_id = %s",
                              (match_id, user["id"])).fetchone()
    side = {match["home_team_id"]: "home", match["away_team_id"]: "away"}
    return {
        "id": match["id"], "sport": match["sport"], "status": match["status"], "role": role,
        "scheduled_start": match["scheduled_start"], "scheduled_minutes": match["scheduled_minutes"],
        "kicked_off_at": match["kicked_off_at"],
        "home_team": match["home_team"], "away_team": match["away_team"],
        "event_types": sorted(_event_types(match)),
        "timed_events": sorted(FOOTBALL_TIMED_EVENTS) if match["sport"] == FOOTBALL else [],
        "lineup": [{"id": r["athlete_id"], "name": r["display_name"], "position": r["position"],
                    "side": side[r["team_id"]], "started": r["started"]} for r in lineup],
        "events": events,
        "last_client_seq": max((e["client_seq"] for e in events), default=0),
        "submission": submission,
    }


@router.post("/matches/{match_id}/kickoff")
def scorer_kickoff(match_id: UUID, user=Depends(require_scorer), conn=Depends(get_conn), now=Depends(utcnow)):
    """The scorer at the pitch starts the match clock when the referee does."""
    _assignment(conn, match_id, user)
    conn.execute("select id from matches where id = %s for update", (match_id,))
    result = kick_off(conn, load_match(conn, match_id, published_only=False), now)
    audit(conn, user["id"], "match.kickoff", "match", match_id)
    return result


@router.post("/matches/{match_id}/events")
def post_events(match_id: UUID, body: EventBatch, user=Depends(require_scorer), conn=Depends(get_conn),
                now=Depends(utcnow)):
    match = load_match(conn, match_id, published_only=False)
    _assignment(conn, match_id, user)
    conn.execute("select id from matches where id = %s for update", (match_id,))
    if match["status"] not in SCORING_STATUSES:
        raise ApiError(409, "not_scoring", f"this match is {match['status']}; events are closed")
    if now < match["scheduled_start"] - EARLY_START:
        raise ApiError(409, "too_early", "scoring opens 30 minutes before kick-off")
    if conn.execute("select 1 from stat_submissions where match_id = %s and scorer_id = %s",
                    (match_id, user["id"])).fetchone():
        raise ApiError(409, "already_submitted", "you've submitted this match; ask an admin to reopen it")
    in_lineup = {r["athlete_id"] for r in lineup_entries(conn, match)}
    if not in_lineup:
        raise ApiError(409, "lineup_missing", "the line-up hasn't been published yet")

    allowed = _event_types(match)
    existing = {r["client_seq"]: r for r in conn.execute(
        """select id, client_seq, athlete_id, event_type, minute, amount, reverses_event_id from stat_events
           where match_id = %s and scorer_id = %s""", (match_id, user["id"])).fetchall()}
    reversed_ids = {r["reverses_event_id"] for r in existing.values() if r["reverses_event_id"]}

    results = []
    for ev in sorted(body.events, key=lambda e: e.client_seq):
        target = existing.get(ev.reverses_client_seq) if ev.reverses_client_seq else None
        prior = existing.get(ev.client_seq)
        if prior is not None:
            same = (prior["athlete_id"] == ev.athlete_id and prior["event_type"] == ev.event_type
                    and prior["minute"] == ev.minute and prior["amount"] == ev.amount
                    and prior["reverses_event_id"] == (target["id"] if target else None))
            results.append({"client_seq": ev.client_seq, "status": "duplicate" if same else "rejected",
                            **({} if same else {"error": "client_seq already used for a different event"})})
            continue
        error = _check_event(ev, match, allowed, in_lineup, target, reversed_ids)
        if error:
            results.append({"client_seq": ev.client_seq, "status": "rejected", "error": error})
            continue
        row = conn.execute(
            """insert into stat_events (match_id, scorer_id, athlete_id, event_type, minute, amount,
                                        reverses_event_id, client_seq)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               returning id, client_seq, athlete_id, event_type, minute, amount, reverses_event_id""",
            (match_id, user["id"], ev.athlete_id, ev.event_type, ev.minute, ev.amount,
             target["id"] if target else None, ev.client_seq),
        ).fetchone()
        existing[ev.client_seq] = row
        if target:
            reversed_ids.add(target["id"])
        results.append({"client_seq": ev.client_seq, "status": "accepted"})

    if match["status"] != "live" and any(r["status"] == "accepted" for r in results):
        conn.execute("update matches set status = 'live' where id = %s", (match_id,))
    return {"results": results, "last_client_seq": max(existing, default=0)}


def _check_event(ev: EventIn, match, allowed, in_lineup, target, reversed_ids) -> str | None:
    if ev.reverses_client_seq is not None:
        if target is None:
            return f"nothing to undo at client_seq {ev.reverses_client_seq}"
        if target["reverses_event_id"] is not None:
            return "an undo can't itself be undone; record the event again instead"
        if target["id"] in reversed_ids:
            return "that event has already been undone"
        if (target["athlete_id"], target["event_type"]) != (ev.athlete_id, ev.event_type):
            return "an undo must name the same athlete and event as the original"
        return None
    if ev.event_type not in allowed:
        return f"{ev.event_type!r} is not an event in {match['sport']}"
    if ev.athlete_id not in in_lineup:
        return "that athlete is not in the published line-up"
    if match["sport"] == FOOTBALL and ev.event_type in FOOTBALL_TIMED_EVENTS and ev.minute is None:
        return f"{ev.event_type} needs the match minute"
    if ev.amount != 1 and ev.event_type != "point":
        return "only basketball points can have an amount above 1"
    return None


@router.post("/matches/{match_id}/submit")
def submit(match_id: UUID, body: SubmitIn, user=Depends(require_scorer), conn=Depends(get_conn)):
    match = load_match(conn, match_id, published_only=False)
    _assignment(conn, match_id, user)
    conn.execute("select id from matches where id = %s for update", (match_id,))
    if match["status"] not in ("lineup_out", "live"):
        raise ApiError(409, "not_scoring", f"this match is {match['status']}")
    if body.shootout_winner and body.home_score != body.away_score:
        raise ApiError(422, "shootout_needs_draw", "a shoot-out winner only applies to a drawn match")
    if conn.execute("select 1 from stat_submissions where match_id = %s and scorer_id = %s",
                    (match_id, user["id"])).fetchone():
        raise ApiError(409, "already_submitted", "you've already submitted this match")
    conn.execute(
        """insert into stat_submissions (match_id, scorer_id, home_score, away_score, shootout_winner)
           values (%s, %s, %s, %s, %s)""",
        (match_id, user["id"], body.home_score, body.away_score, body.shootout_winner),
    )
    pending = conn.execute(
        """select count(*) as n from match_scorers s where s.match_id = %s and not exists
           (select 1 from stat_submissions x where x.match_id = s.match_id and x.scorer_id = s.user_id)""",
        (match_id,),
    ).fetchone()["n"]
    status = "final_pending" if pending == 0 else "live"
    conn.execute("update matches set status = %s where id = %s", (status, match_id))
    return {"match_id": match_id, "status": status, "waiting_for_scorers": pending}
