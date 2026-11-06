"""Contest page data: Rules (from the scoring engine) and Winnings (payout preview)."""
from tests.conftest import auth, make_user, valid_picks
from tests.test_api_pilot import _free_contest, _team


def test_sport_rules_come_from_the_engine(client):
    r = client.get("/sports/football/rules").json()
    assert (r["team_size"], r["max_per_side"], r["max_teams_per_match"]) == (11, 7, 10)
    assert r["multipliers"] == {"captain": 2.5, "vice_captain": 2.0, "key": 1.5}
    pts = {s["event"]: s["points"] for s in r["scoring"]}
    assert pts["Goal (FWD)"] == 40 and pts["Goal (DEF)"] == 60 and pts["Assist"] == 20
    assert pts["In the starting line-up"] == 4 and pts["Penalty miss"] == -20
    assert any(e.startswith("Clean sheet") and p == 20 for e, p in pts.items())
    assert r["late_join"] == {"until_share": 0.67, "fee_multiplier": 1.5}
    assert [g["name"] for g in r["positions"]] == ["goalkeeper", "defenders", "midfielders", "forwards"]
    assert client.get("/sports/basketball/rules").json()["team_size"] == 8
    assert client.get("/sports/handball/rules").status_code == 404


def test_free_contest_winnings_show_the_prize_text(world, client):
    c = _free_contest(client, world["match"]["id"])
    p = client.get(f"/contests/{c['id']}/payout-preview").json()
    assert p["free"] and p["maximum"] is None and p["max_entries"] == 1000


def test_paid_contest_winnings_maximum_and_current(world, client, db):
    mid, n = world["match"]["id"], None
    cid = db.execute("""insert into contests (match_id, name, capacity, entry_fee_kobo, min_fill, team_cap)
                        values (%s, 'Paid 100', 100, 100000, 20, 6) returning id""", (mid,)).fetchone()["id"]
    p = client.get(f"/contests/{cid}/payout-preview").json()
    assert not p["free"] and p["current"] is None
    mx = p["maximum"]
    assert mx["entries"] == 100 and mx["pool_kobo"] == 6_000_000 and mx["ranks_paid"] == 40
    assert mx["rows"][0] == {"from": 1, "to": 1, "prize_kobo": 1_504_000}            # N15,040 (PRD 6.9)
    assert mx["rows"][-1] == {"from": 26, "to": 40, "prize_kobo": 100_000}           # money back band
    assert sum((r["to"] - r["from"] + 1) * r["prize_kobo"] for r in mx["rows"]) == mx["pool_kobo"]

    from tests.conftest import athletes_by_name
    names = athletes_by_name(db, mid)
    for i, fee in enumerate((100_000, 100_000, 150_000)):          # one late entry paid 150%
        u = make_user(db, world["school"], team_name=f"payer_{i}")
        t = _team(client, u, mid, valid_picks(names))
        db.execute("insert into contest_entries (contest_id, fantasy_team_id, user_id, fee_kobo) values (%s, %s, %s, %s)",
                   (cid, t, u, fee))
    cur = client.get(f"/contests/{cid}/payout-preview").json()["current"]
    assert cur["entries"] == 3 and cur["pool_kobo"] == 350_000 * 60 // 100
    assert n is None and cur["ranks_paid"] == 1
