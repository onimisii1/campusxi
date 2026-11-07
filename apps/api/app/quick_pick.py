"""Quick pick: a random team that keeps the player's own picks, obeys every team rule, and differs
from every team already saved for the match, so two players rarely get the same side.

Filling greedily in a fixed order can paint itself into a corner. For example, when one side lists
every player as a midfielder, the goalkeeper, defenders and forwards must all come from the other side
(at most 7), so taking that side's midfielders first leaves no room for a forward. So each attempt
fills the scarcest positions first, every attempt is checked with the real validator, and failed
attempts are simply retried in a new random order.
"""
import random

from app.engines.scoring import Pick, SquadAthlete, team_signature, validate_team
from app.engines.scoring.rules import CAPTAIN, KEY, NONE, TEAM_RULES, VICE_CAPTAIN

ROLES = (CAPTAIN, VICE_CAPTAIN, KEY)
ATTACK = {"FWD": 0, "MID": 1, "DEF": 2, "GK": 3}       # captains lean attacking (football); others: any


def _attempt(sport, squad, lineup, keep, rng) -> list:
    rules = TEAM_RULES[sport]
    by_id = {a.athlete_id: a for a in squad}
    picks = {aid: role for aid, role in keep.items() if aid in by_id}

    def group_of(a):
        return next((i for i, g in enumerate(rules.groups) if a.position in g.positions), None)

    def count(pred):
        return sum(1 for aid in picks if pred(by_id[aid]))

    def can_add(a):
        gi = group_of(a)
        if a.athlete_id in picks or gi is None or len(picks) >= rules.size:
            return False
        g = rules.groups[gi]
        if g.max is not None and count(lambda b: group_of(b) == gi) >= g.max:
            return False
        return count(lambda b: b.team_id == a.team_id) < rules.max_per_side

    # Announced starters are preferred, but only loosely, so teams still vary.
    rank = {True: 0.0, None: 0.6, False: 1.2}
    order = sorted(squad, key=lambda a: rank[lineup.get(a.athlete_id)] + rng.random() * 1.5)
    scarce = sorted(range(len(rules.groups)),
                    key=lambda gi: (sum(1 for a in squad if group_of(a) == gi), rng.random()))
    for gi in scarce:
        for a in order:
            if count(lambda b: group_of(b) == gi) >= rules.groups[gi].min:
                break
            if group_of(a) == gi and can_add(a):
                picks[a.athlete_id] = NONE
    for a in order:
        if len(picks) >= rules.size:
            break
        if can_add(a):
            picks[a.athlete_id] = NONE

    taken = set(picks.values())
    free = sorted((aid for aid, r in picks.items() if r == NONE),
                  key=lambda aid: ATTACK.get(by_id[aid].position, 1) + rng.random() * 2.5)
    for role in ROLES:
        if role not in taken and free:
            picks[free.pop(0)] = role
    return [Pick(aid, role) for aid, role in picks.items()]


def quick_pick(sport: str, squad: list, lineup: dict, keep: dict, others: list, rng=None,
               tries: int = 600) -> tuple:
    """(picks, unique) or (None, False) when the kept picks can't make a valid team.

    lineup: {athlete_id: True starting / False bench}; keep: {athlete_id: role} to keep;
    others: lists of Pick for every team already saved for this match (anyone's).
    unique is True when no saved team has the same eleven; otherwise at least the roles differ."""
    rng = rng or random.Random()
    sets = {frozenset(p.athlete_id for p in t) for t in others}
    sigs = {team_signature(t) for t in others}
    fallback = None
    for _ in range(tries):
        picks = _attempt(sport, squad, lineup, keep, rng)
        if validate_team(sport, picks, squad):
            continue
        if frozenset(p.athlete_id for p in picks) not in sets:
            return picks, True
        if fallback is None and team_signature(picks) not in sigs:
            fallback = picks
    return (fallback, False) if fallback else (None, False)


__all__ = ["quick_pick", "SquadAthlete"]
