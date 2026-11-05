"""Fantasy team validation and team points (PRD 5.3, 6.1, 6.2).

Pricing is uniform, so there is no budget: a team is valid when it has the right
size, meets every position group, respects the per-side cap and has exactly one
Captain, Vice-captain and Key player.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from .rules import CAPTAIN, KEY, MULTIPLIERS, NONE, POSITIONS, TEAM_RULES, VICE_CAPTAIN


@dataclass(frozen=True)
class SquadAthlete:
    athlete_id: str
    team_id: str
    position: str


@dataclass(frozen=True)
class Pick:
    athlete_id: str
    role: str = NONE


def validate_team(sport: str, picks, squad) -> list:
    """Return a list of human-readable errors; an empty list means the team is valid."""
    rules = TEAM_RULES[sport]
    by_id = {a.athlete_id: a for a in squad}
    errors = []

    ids = [p.athlete_id for p in picks]
    if len(ids) != rules.size:
        errors.append(f"pick exactly {rules.size} athletes (got {len(ids)})")
    dupes = [a for a, n in Counter(ids).items() if n > 1]
    if dupes:
        errors.append(f"athletes picked more than once: {', '.join(sorted(dupes))}")
    unknown = [a for a in ids if a not in by_id]
    if unknown:
        errors.append(f"athletes not in this match's squads: {', '.join(sorted(set(unknown)))}")
        return errors

    athletes = [by_id[a] for a in dict.fromkeys(ids)]
    bad_pos = [a.athlete_id for a in athletes if a.position not in POSITIONS[sport]]
    if bad_pos:
        errors.append(f"unknown positions for {sport}: {', '.join(bad_pos)}")
    for g in rules.groups:
        n = sum(1 for a in athletes if a.position in g.positions)
        if n < g.min:
            errors.append(f"need at least {g.min} {g.name} (got {n})")
        if g.max is not None and n > g.max:
            errors.append(f"at most {g.max} {g.name} allowed (got {n})")
    for team_id, n in Counter(a.team_id for a in athletes).items():
        if n > rules.max_per_side:
            errors.append(f"at most {rules.max_per_side} athletes from one side ({team_id} has {n})")

    roles = Counter(p.role for p in picks)
    for role, label in ((CAPTAIN, "Captain"), (VICE_CAPTAIN, "Vice-captain"), (KEY, "Key player")):
        if roles[role] != 1:
            errors.append(f"choose exactly one {label} (got {roles[role]})")
    stray = set(roles) - {CAPTAIN, VICE_CAPTAIN, KEY, NONE}
    if stray:
        errors.append(f"unknown roles: {', '.join(sorted(stray))}")
    return errors


def team_signature(picks) -> frozenset:
    """Two teams with the same signature are duplicates and must be rejected (PRD C3)."""
    return frozenset((p.athlete_id, p.role) for p in picks)


def team_points(picks, scores) -> tuple:
    """Return (total, [(athlete_id, role, base_points, multiplied_points)])."""
    total = Decimal("0")
    lines = []
    for p in picks:
        base = scores[p.athlete_id].points if p.athlete_id in scores else Decimal("0")
        pts = base * MULTIPLIERS[p.role]
        total += pts
        lines.append((p.athlete_id, p.role, base, pts))
    return total, lines
