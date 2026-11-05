"""Scoring engine tests (PRD 6.1–6.6). Values are the PRD's confirmed tables."""
from decimal import Decimal as D

import pytest

from app.engines.scoring import (
    BASKETBALL, FOOTBALL, VOLLEYBALL, LineupEntry, MatchContext, Pick, SquadAthlete,
    StatEvent, score_match, team_points, team_signature, validate_team,
)

FB = MatchContext(FOOTBALL, "home", "away", scheduled_minutes=90)


def lineup(*rows):
    return [LineupEntry(a, t, pos, started) for a, t, pos, started in rows]


def events(*rows):
    out = []
    for i, row in enumerate(rows, start=1):
        athlete, etype, minute, *rest = row
        kwargs = rest[0] if rest else {}
        out.append(StatEvent(i, athlete, etype, minute, **kwargs))
    return out


def points(ctx, lu, evs):
    return {k: v.points for k, v in score_match(ctx, lu, evs).items()}


# ---------- football ----------

def test_goal_values_by_position():
    lu = lineup(("fwd", "home", "FWD", True), ("mid", "home", "MID", True),
                ("def", "away", "DEF", True), ("gk", "away", "GK", True))
    evs = events(("fwd", "goal", 10), ("mid", "goal", 20), ("def", "goal", 30), ("gk", "goal", 40))
    p = points(FB, lu, evs)
    assert p["fwd"] == 44 and p["mid"] == 54
    # away DEF/GK each score 60, and away conceded 2 goals while they were on (-2 each)
    assert p["def"] == 4 + 60 - 4
    assert p["gk"] == 4 + 60 - 4


def test_goalkeeper_clean_sheet_and_saves():
    lu = lineup(("gk", "home", "GK", True))
    evs = events(("gk", "save", 15), ("gk", "save", 50), ("gk", "save", 88), ("gk", "penalty_save", 60))
    assert points(FB, lu, evs)["gk"] == 4 + 20 + 3 * 6 + 50


def test_defender_concedes_no_clean_sheet():
    lu = lineup(("def", "home", "DEF", True), ("striker", "away", "FWD", True))
    evs = events(("striker", "goal", 30))
    assert points(FB, lu, evs)["def"] == 4 - 2


def test_clean_sheet_needs_60_percent_and_counts_only_goals_while_on_pitch():
    lu = lineup(("def55", "home", "DEF", True), ("def50", "home", "DEF", True),
                ("striker", "away", "FWD", True))
    evs = events(("def55", "sub_off", 55), ("def50", "sub_off", 50), ("striker", "goal", 80))
    p = points(FB, lu, evs)
    assert p["def55"] == 4 + 20      # 55 of 90 minutes >= 54, goal came after he left
    assert p["def50"] == 4           # 50 minutes < 54: no clean sheet, no concede


def test_live_clean_sheet_only_after_enough_minutes_played():
    lu = lineup(("gk", "home", "GK", True), ("striker", "away", "FWD", True))
    at = lambda m: MatchContext(FOOTBALL, "home", "away", 90, elapsed_minutes=m)  # noqa: E731
    assert points(at(1), lu, [])["gk"] == 4                 # minute 1: no clean sheet yet
    assert points(at(53), lu, [])["gk"] == 4                # 53 < 54 (60% of 90)
    assert points(at(54), lu, [])["gk"] == 24               # provisional clean sheet
    assert points(at(70), lu, events(("striker", "goal", 65)))["gk"] == 4 - 2   # lost on conceding
    # a late event minute beyond the wall clock still counts as time played
    assert points(at(10), lu, events(("gk", "save", 60)))["gk"] == 4 + 6 + 20


def test_substitute_gets_two_and_short_stint_has_no_clean_sheet():
    lu = lineup(("sub", "home", "DEF", False), ("bench", "home", "MID", False))
    evs = events(("sub", "sub_on", 70))
    p = points(FB, lu, evs)
    assert p["sub"] == 2
    assert p["bench"] == 0           # never came on: 0 points


def test_own_goal_counts_against_own_team():
    lu = lineup(("gk", "home", "GK", True), ("def", "home", "DEF", True), ("fwd", "away", "FWD", True))
    evs = events(("def", "own_goal", 20))
    p = points(FB, lu, evs)
    assert p["gk"] == 4 - 2
    assert p["def"] == 4 - 8 - 2
    assert p["fwd"] == 4


def test_red_card_ends_time_on_pitch():
    lu = lineup(("def", "home", "DEF", True), ("fwd", "away", "FWD", True))
    evs = events(("def", "red", 40), ("fwd", "goal", 50))
    assert points(FB, lu, evs)["def"] == 4 - 10


def test_cards_and_penalty_miss():
    lu = lineup(("fwd", "home", "FWD", True))
    evs = events(("fwd", "yellow", 10), ("fwd", "penalty_miss", 30), ("fwd", "assist", 44))
    assert points(FB, lu, evs)["fwd"] == 4 - 4 - 20 + 20


def test_correction_reverses_event():
    lu = lineup(("fwd", "home", "FWD", True))
    evs = events(("fwd", "goal", 10), ("fwd", "goal", 10, {"reverses_event_id": 1}))
    assert points(FB, lu, evs)["fwd"] == 4


def test_breakdown_explains_points():
    lu = lineup(("mid", "home", "MID", True))
    score = score_match(FB, lu, events(("mid", "goal", 5), ("mid", "assist", 9)))["mid"]
    assert score.breakdown == [("In starting line-up", 4), ("Goal (MID)", 50), ("Assist", 20)]


def test_rejects_bad_events():
    lu = lineup(("fwd", "home", "FWD", True))
    with pytest.raises(ValueError, match="unknown type"):
        score_match(FB, lu, events(("fwd", "shot_on_target", 5)))   # dropped in v1
    with pytest.raises(ValueError, match="needs a minute"):
        score_match(FB, lu, events(("fwd", "goal", None)))
    with pytest.raises(ValueError, match="not in lineup"):
        score_match(FB, lu, events(("ghost", "assist", 5)))


# ---------- basketball / volleyball ----------

def test_basketball_scoring():
    ctx = MatchContext(BASKETBALL, "home", "away", scheduled_minutes=40)
    lu = lineup(("pg", "home", "G", True), ("bench", "home", "F", False))
    evs = events(("pg", "point", None, {"amount": 2}), ("pg", "point", None, {"amount": 3}),
                 *[("pg", "rebound", None)] * 5, ("pg", "assist", None), ("pg", "steal", None),
                 ("pg", "block", None), ("pg", "turnover", None), ("bench", "sub_on", 12))
    p = points(ctx, lu, evs)
    assert p["pg"] == D(4) + 5 + D("6.0") + D("1.5") + 3 + 3 - 1
    assert p["bench"] == 2


def test_volleyball_scoring():
    ctx = MatchContext(VOLLEYBALL, "home", "away", scheduled_minutes=0)
    lu = lineup(("oh", "home", "OH", True))
    evs = events(("oh", "kill", None), ("oh", "kill", None), ("oh", "ace", None), ("oh", "block", None),
                 ("oh", "dig", None), ("oh", "set_assist", None), ("oh", "service_error", None),
                 ("oh", "attack_error", None))
    assert points(ctx, lu, evs)["oh"] == 4 + 6 + 4 + 3 + 1 + 1 - 1 - 1


# ---------- team validation and multipliers ----------

def football_squad():
    squad = []
    for side in ("home", "away"):
        squad += [SquadAthlete(f"{side}-gk", side, "GK")]
        squad += [SquadAthlete(f"{side}-def{i}", side, "DEF") for i in range(5)]
        squad += [SquadAthlete(f"{side}-mid{i}", side, "MID") for i in range(5)]
        squad += [SquadAthlete(f"{side}-fwd{i}", side, "FWD") for i in range(3)]
    return squad


def valid_picks():
    ids = (["home-gk", "home-def0", "home-def1", "home-def2", "home-mid0", "home-mid1", "home-fwd0",
            "away-def0", "away-mid0", "away-fwd0", "away-fwd1"])
    roles = {"home-fwd0": "captain", "away-fwd0": "vice_captain", "home-mid0": "key"}
    return [Pick(a, roles.get(a, "none")) for a in ids]


def test_valid_football_team():
    assert validate_team(FOOTBALL, valid_picks(), football_squad()) == []


def test_team_errors():
    squad = football_squad()
    picks = valid_picks()
    no_gk = [Pick("home-def3") if p.athlete_id == "home-gk" else p for p in picks]
    assert "need at least 1 goalkeeper (got 0)" in validate_team(FOOTBALL, no_gk, squad)

    eight_home = [Pick("home-mid2") if p.athlete_id == "away-def0" else p for p in picks]
    assert any("at most 7 athletes from one side" in e for e in validate_team(FOOTBALL, eight_home, squad))

    two_captains = [Pick(p.athlete_id, "captain") if p.role == "key" else p for p in picks]
    errs = validate_team(FOOTBALL, two_captains, squad)
    assert "choose exactly one Captain (got 2)" in errs and "choose exactly one Key player (got 0)" in errs

    assert "pick exactly 11 athletes (got 10)" in validate_team(FOOTBALL, picks[:10], squad)
    dup = picks[:10] + [Pick("home-gk")]
    assert any("more than once" in e for e in validate_team(FOOTBALL, dup, squad))


def test_volleyball_attackers_group():
    squad = [SquadAthlete(a, side, pos) for side in ("home", "away")
             for a, pos in ((f"{side}-s", "S"), (f"{side}-oh", "OH"), (f"{side}-opp", "OPP"),
                            (f"{side}-mb", "MB"), (f"{side}-l", "L"), (f"{side}-oh2", "OH"))]
    ids = ["home-s", "home-oh", "away-opp", "home-mb", "away-l", "away-oh", "away-mb"]
    roles = {"home-s": "captain", "home-oh": "vice_captain", "away-l": "key"}
    picks = [Pick(a, roles.get(a, "none")) for a in ids]
    assert validate_team(VOLLEYBALL, picks, squad) == []


def test_team_points_apply_multipliers():
    lu = lineup(("c", "home", "FWD", True), ("vc", "home", "MID", True),
                ("k", "away", "DEF", True), ("x", "away", "MID", False))
    scores = score_match(FB, lu, events(("c", "goal", 10)))
    picks = [Pick("c", "captain"), Pick("vc", "vice_captain"), Pick("k", "key"), Pick("x")]
    total, lines = team_points(picks, scores)
    # C 44×2.5, VC 4×2, K (4 − 2 conceded)×1.5, x did not play
    assert total == D("110") + 8 + D("3") + 0
    assert lines[0] == ("c", "captain", 44, D("110.0"))


def test_duplicate_team_signature():
    a = valid_picks()
    assert team_signature(a) == team_signature(list(reversed(a)))
    swapped = [Pick(p.athlete_id, "none") if p.role == "key" else p for p in a]
    assert team_signature(a) != team_signature(swapped)
