"""Athlete points from the append-only stat event stream (PRD 6.3–6.6, 6.13).

Points are always recomputed from the full event stream; nothing is mutated.
A correction is a new event with `reverses_event_id` set, which cancels both.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .rules import FOOTBALL, SCORING_RULES, CURRENT_VERSION, ScoringRules

STRUCTURAL_EVENTS = {"sub_on", "sub_off"}
FOOTBALL_TIMED_EVENTS = {"sub_on", "sub_off", "red", "goal", "own_goal"}


@dataclass(frozen=True)
class LineupEntry:
    athlete_id: str
    team_id: str
    position: str
    started: bool


@dataclass(frozen=True)
class StatEvent:
    id: int
    athlete_id: str
    type: str
    minute: int | None = None
    amount: int = 1
    reverses_event_id: int | None = None


@dataclass(frozen=True)
class MatchContext:
    sport: str
    home_team_id: str
    away_team_id: str
    scheduled_minutes: int
    rules_version: str | None = None

    @property
    def rules(self) -> ScoringRules:
        return SCORING_RULES[self.rules_version or CURRENT_VERSION[self.sport]]


@dataclass
class AthleteScore:
    athlete_id: str
    points: Decimal = Decimal("0")
    breakdown: list = field(default_factory=list)  # [(label, points)] for explainability

    def add(self, label: str, pts: Decimal):
        if pts:
            self.points += pts
            self.breakdown.append((label, pts))


def effective_events(events):
    """Drop correction events and the events they reverse."""
    reversed_ids = {e.reverses_event_id for e in events if e.reverses_event_id is not None}
    return [e for e in events if e.reverses_event_id is None and e.id not in reversed_ids]


def score_match(ctx: MatchContext, lineup, events) -> dict:
    """Return {athlete_id: AthleteScore} for every athlete in the lineup."""
    rules = ctx.rules
    if rules.sport != ctx.sport:
        raise ValueError(f"rules {rules.version} are not for {ctx.sport}")
    by_id = {entry.athlete_id: entry for entry in lineup}
    evs = effective_events(events)
    for e in evs:
        if e.athlete_id not in by_id:
            raise ValueError(f"event {e.id} references athlete {e.athlete_id} not in lineup")
        known = rules.events.keys() | rules.position_events.keys() | STRUCTURAL_EVENTS
        if e.type not in known:
            raise ValueError(f"event {e.id}: unknown type {e.type!r} for {ctx.sport}")
        if ctx.sport == FOOTBALL and e.type in FOOTBALL_TIMED_EVENTS and e.minute is None:
            raise ValueError(f"event {e.id}: {e.type} needs a minute")

    scores = {}
    for entry in lineup:
        mine = [e for e in evs if e.athlete_id == entry.athlete_id]
        score = AthleteScore(entry.athlete_id)
        scores[entry.athlete_id] = score
        subbed_on = any(e.type == "sub_on" for e in mine)
        if entry.started:
            score.add("In starting line-up", rules.appearance["start"])
        elif subbed_on:
            score.add("Came on as substitute", rules.appearance["sub_on"])
        else:
            continue  # did not play: 0 points (PRD 6.6)

        for e in mine:
            if e.type in STRUCTURAL_EVENTS:
                continue
            if e.type in rules.position_events:
                pts = rules.position_events[e.type].get(entry.position, Decimal("0"))
                score.add(f"{_label(e.type)} ({entry.position})", pts * e.amount)
            else:
                score.add(_label(e.type, e.amount), rules.events[e.type] * e.amount)

        if ctx.sport == FOOTBALL:
            _football_defence(ctx, rules, entry, mine, evs, by_id, score)
    return scores


def _football_defence(ctx, rules, entry, mine, evs, by_id, score):
    start = 0 if entry.started else min(e.minute for e in mine if e.type == "sub_on")
    match_end = max([ctx.scheduled_minutes] + [e.minute for e in evs if e.minute is not None])
    exits = [e.minute for e in mine if e.type in ("sub_off", "red") and e.minute >= start]
    end = min(exits) if exits else match_end

    # Goals against this athlete's team: opponents' goals plus own team's own goals.
    against = [e.minute for e in evs
               if (e.type == "goal" and by_id[e.athlete_id].team_id != entry.team_id)
               or (e.type == "own_goal" and by_id[e.athlete_id].team_id == entry.team_id)]
    conceded_on_pitch = sum(1 for m in against if start <= m < end)

    if entry.position in rules.goal_conceded_positions and conceded_on_pitch:
        score.add(f"Goals conceded on pitch ×{conceded_on_pitch}",
                  rules.goal_conceded * conceded_on_pitch)
    if (entry.position in rules.clean_sheet_positions and conceded_on_pitch == 0
            and (end - start) >= rules.clean_sheet_min_share * ctx.scheduled_minutes):
        score.add("Clean sheet", rules.clean_sheet)


def _label(event_type: str, amount: int = 1) -> str:
    text = event_type.replace("_", " ").capitalize()
    return f"{text} ×{amount}" if amount != 1 else text
