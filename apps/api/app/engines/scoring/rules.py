"""Scoring rule versions and team-composition rules per sport (PRD 6.1–6.5).

A match pins the rule version that was active at lock, so values can be tuned
(e.g. after the pilot) by adding a new version rather than editing an old one.
"""
from dataclasses import dataclass, field
from decimal import Decimal

FOOTBALL = "football"
BASKETBALL = "basketball"
VOLLEYBALL = "volleyball"

# Role multipliers, all sports (FantasyFi rule).
CAPTAIN = "captain"
VICE_CAPTAIN = "vice_captain"
KEY = "key"
NONE = "none"
MULTIPLIERS = {
    CAPTAIN: Decimal("2.5"),
    VICE_CAPTAIN: Decimal("2"),
    KEY: Decimal("1.5"),
    NONE: Decimal("1"),
}

MAX_TEAMS_PER_MATCH = 10


@dataclass(frozen=True)
class PositionGroup:
    """At least `min` and at most `max` picks from `positions`."""
    name: str
    positions: frozenset
    min: int
    max: int | None = None


@dataclass(frozen=True)
class TeamRules:
    size: int
    max_per_side: int
    groups: tuple


@dataclass(frozen=True)
class ScoringRules:
    sport: str
    version: str
    appearance: dict                 # {"start": n, "sub_on": n}
    events: dict                     # event_type -> points (flat)
    position_events: dict = field(default_factory=dict)  # event_type -> {position: points}
    # Football-only extras; ignored by other sports.
    clean_sheet: Decimal = Decimal("0")
    clean_sheet_positions: frozenset = frozenset()
    clean_sheet_min_share: Decimal = Decimal("0")
    goal_conceded: Decimal = Decimal("0")
    goal_conceded_positions: frozenset = frozenset()


D = Decimal

FOOTBALL_V1 = ScoringRules(
    sport=FOOTBALL,
    version="football-v1",
    appearance={"start": D(4), "sub_on": D(2)},
    events={
        "assist": D(20),
        "save": D(6),
        "penalty_save": D(50),
        "yellow": D(-4),
        "red": D(-10),
        "own_goal": D(-8),
        "penalty_miss": D(-20),
    },
    position_events={"goal": {"FWD": D(40), "MID": D(50), "DEF": D(60), "GK": D(60)}},
    clean_sheet=D(20),
    clean_sheet_positions=frozenset({"GK", "DEF"}),
    clean_sheet_min_share=D("0.6"),
    goal_conceded=D(-2),
    goal_conceded_positions=frozenset({"GK", "DEF"}),
)

# Draft values: validated in the pilot, then locked as a new version (PRD 10, Phase 4).
BASKETBALL_V1 = ScoringRules(
    sport=BASKETBALL,
    version="basketball-v1-draft",
    appearance={"start": D(4), "sub_on": D(2)},
    events={
        "point": D(1),          # one event per point scored; `amount` carries 1, 2 or 3
        "rebound": D("1.2"),
        "assist": D("1.5"),
        "steal": D(3),
        "block": D(3),
        "turnover": D(-1),
    },
)

VOLLEYBALL_V1 = ScoringRules(
    sport=VOLLEYBALL,
    version="volleyball-v1-draft",
    appearance={"start": D(4), "sub_on": D(2)},
    events={
        "kill": D(3),
        "ace": D(4),
        "block": D(3),
        "dig": D(1),
        "set_assist": D(1),
        "service_error": D(-1),
        "attack_error": D(-1),
    },
)

SCORING_RULES = {r.version: r for r in (FOOTBALL_V1, BASKETBALL_V1, VOLLEYBALL_V1)}
CURRENT_VERSION = {FOOTBALL: FOOTBALL_V1.version, BASKETBALL: BASKETBALL_V1.version,
                   VOLLEYBALL: VOLLEYBALL_V1.version}

TEAM_RULES = {
    FOOTBALL: TeamRules(size=11, max_per_side=7, groups=(
        PositionGroup("goalkeeper", frozenset({"GK"}), 1, 1),
        PositionGroup("defenders", frozenset({"DEF"}), 3, 5),
        PositionGroup("midfielders", frozenset({"MID"}), 3, 5),
        PositionGroup("forwards", frozenset({"FWD"}), 1, 3),
    )),
    BASKETBALL: TeamRules(size=8, max_per_side=5, groups=(
        PositionGroup("guards", frozenset({"G"}), 2),
        PositionGroup("forwards", frozenset({"F"}), 2),
        PositionGroup("centres", frozenset({"C"}), 1),
    )),
    VOLLEYBALL: TeamRules(size=7, max_per_side=4, groups=(
        PositionGroup("setters", frozenset({"S"}), 1),
        PositionGroup("attackers", frozenset({"OH", "OPP"}), 2),
        PositionGroup("middles", frozenset({"MB"}), 1),
        PositionGroup("liberos", frozenset({"L"}), 1),
    )),
}

POSITIONS = {sport: frozenset().union(*(g.positions for g in rules.groups))
             for sport, rules in TEAM_RULES.items()}
