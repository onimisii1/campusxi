"""Quick pick: always a valid team (forwards included), keeps your picks, differs from other players'."""
import random

from app.engines.scoring import Pick, SquadAthlete, validate_team
from app.quick_pick import quick_pick
from tests.conftest import auth, make_user
from tests.test_api_pilot import _free_contest, _team
from tests.test_api_scorer import sw  # noqa: F401  (sw is a fixture)
from tests.test_api_teams import _variants

# The NUESA EEE v PGE shape: one side lists every player as a midfielder, so GK, DEF and FWD must all
# come from the other side (at most 7 per side).
HOME = ([("GK", 1), ("DEF", 7), ("MID", 5), ("FWD", 5)])
SQUAD = [SquadAthlete(f"h{pos}{i}", "home", pos) for pos, n in HOME for i in range(n)] + \
        [SquadAthlete(f"aMID{i}", "away", "MID") for i in range(18)]


def test_every_quick_pick_is_valid_and_has_a_forward_even_when_one_side_is_all_midfielders():
    for seed in range(300):
        picks, _ = quick_pick("football", SQUAD, {}, {}, [], random.Random(seed))
        assert validate_team("football", picks, SQUAD) == [], seed
        assert any(p.athlete_id.startswith("hFWD") for p in picks)


def test_keeps_your_picks_and_says_when_they_cant_work():
    keep = {"hFWD0": "captain", "aMID3": "none"}
    picks, _ = quick_pick("football", SQUAD, {}, keep, [], random.Random(1))
    got = {p.athlete_id: p.role for p in picks}
    assert got["hFWD0"] == "captain" and got["aMID3"] == "none"
    assert sorted(r for r in got.values() if r != "none") == ["captain", "key", "vice_captain"]
    # Seven home defenders/midfielders leave no room for the home-only goalkeeper.
    stuck = {f"hDEF{i}": "none" for i in range(5)} | {"hMID0": "none", "hMID1": "none"}
    assert quick_pick("football", SQUAD, {}, stuck, [], random.Random(1)) == (None, False)


def test_players_get_different_elevens():
    others, sets = [], set()
    rng = random.Random(3)
    for _ in range(40):
        picks, unique = quick_pick("football", SQUAD, {}, {}, others, rng)
        assert unique
        ids = frozenset(p.athlete_id for p in picks)
        assert ids not in sets
        sets.add(ids)
        others.append(picks)


def test_basketball_is_positionless():
    squad = [SquadAthlete(f"{s}{i}", s, "P") for s in ("home", "away") for i in range(9)]
    picks, unique = quick_pick("basketball", squad, {}, {}, [[Pick("x", "none")]], random.Random(5))
    assert validate_team("basketball", picks, squad) == [] and unique


def test_quick_pick_api_saves_cleanly_and_two_players_get_different_teams(sw, client, db):
    mid = sw["match"]["id"]
    a, b = make_user(db, sw["school"], team_name="qp_one"), make_user(db, sw["school"], team_name="qp_two")
    first = client.post(f"/matches/{mid}/quick-pick", headers=auth(a), json={}).json()
    assert first["unique"] is True
    saved = client.post(f"/matches/{mid}/teams", headers=auth(a), json={"picks": first["picks"]})
    assert saved.status_code == 201, saved.json()
    second = client.post(f"/matches/{mid}/quick-pick", headers=auth(b), json={}).json()
    assert {p["athlete_id"] for p in second["picks"]} != {p["athlete_id"] for p in first["picks"]}
    keep = [first["picks"][0]]
    third = client.post(f"/matches/{mid}/quick-pick", headers=auth(b), json={"picks": keep}).json()
    assert keep[0] in third["picks"]
    assert client.post(f"/matches/{mid}/quick-pick", json={}).status_code == 401


def test_ties_share_a_rank_and_the_team_put_in_first_is_listed_first(sw, client, db):
    mid, n = sw["match"]["id"], sw["names"]
    v = _variants(n, 3)
    early, late = make_user(db, sw["school"], team_name="zz_early"), make_user(db, sw["school"], team_name="aa_late")
    t_early = _team(client, early, mid, v[1])
    t_late = _team(client, late, mid, v[2])
    c = _free_contest(client, mid)
    for user, team in ((late, t_late), (early, t_early)):             # the later team joins first
        assert client.post(f"/contests/{c['id']}/entries", headers=auth(user),
                           json={"fantasy_team_id": team}).status_code == 201
    rows = client.get(f"/contests/{c['id']}/leaderboard").json()["entries"]
    assert [(r["team_name"], r["rank"], r["shared"]) for r in rows] == [("zz_early", 1, True), ("aa_late", 1, True)]
