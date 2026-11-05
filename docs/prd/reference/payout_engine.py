"""Reference payout + P2P settlement engine for the CampusXI PRD.

Computes every worked example that appears in the PRD so the document's numbers
are generated, not hand-typed. Writes examples.json next to this file.
"""
import json
import math
import os

PAID_SHARE = 0.40      # top 40% of ranks are paid
PROFIT_SHARE = 0.25    # top 25% of ranks profit
FLOOR_MULT = 1.2       # every profit rank gets at least 1.2x entry
ROUND_TO = 10          # prizes rounded down to N10; residue to 1st

# size tier -> (platform fee, target 1st-prize share of pool); flat 40% fee confirmed
TIERS = [
    (2, 0.40, None),      # 1v1: winner takes all
    (20, 0.40, 0.50),
    (200, 0.40, 0.25),
    (1000, 0.40, 0.15),
]


def tier_for(n):
    for max_n, rake, first in TIERS:
        if n <= max_n:
            return rake, first
    raise ValueError("contest size above 1,000 cap")


def bands(n):
    if n == 2:
        return 1, 1
    w = max(1, math.floor(PROFIT_SHARE * n))
    p = max(w, math.floor(PAID_SHARE * n))
    return p, w


def payout_table(n, entry, rake=None, first_share=None):
    t_rake, t_first = tier_for(n)
    rake = t_rake if rake is None else rake
    first_share = t_first if first_share is None else first_share
    gross = n * entry
    pool = round(gross * (1 - rake))
    if n == 2:
        return {"n": n, "entry": entry, "rake": rake, "gross": gross, "pool": pool,
                "paid": 1, "profit": 1, "alpha": None, "prizes": [pool]}
    p, w = bands(n)
    breakeven = (p - w) * entry
    r = pool - breakeven
    floor_each = FLOOR_MULT * entry
    extra = r - w * floor_each
    if extra < 0:
        raise ValueError(f"rake {rake:.0%} cannot fund bands for n={n}")

    def first_for(alpha):
        weights = [1 / (i ** alpha) for i in range(1, w + 1)]
        return floor_each + extra * weights[0] / sum(weights)

    target = first_share * pool
    if first_for(0) >= target:
        alpha = 0.0
    elif first_for(20) <= target:
        alpha = 20.0
    else:
        lo, hi = 0.0, 20.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if first_for(mid) < target:
                lo = mid
            else:
                hi = mid
        alpha = (lo + hi) / 2

    weights = [1 / (i ** alpha) for i in range(1, w + 1)]
    total_w = sum(weights)
    profit = [math.floor((floor_each + extra * wt / total_w) / ROUND_TO) * ROUND_TO
              for wt in weights]
    profit[0] += r - sum(profit)
    prizes = profit + [entry] * (p - w)
    return {"n": n, "entry": entry, "rake": rake, "gross": gross, "pool": pool,
            "paid": p, "profit": w, "alpha": round(alpha, 3), "prizes": prizes}


def check_table(t):
    prizes = t["prizes"]
    assert sum(prizes) == t["pool"], "pool must sum exactly"
    assert all(a >= b for a, b in zip(prizes, prizes[1:])), "non-increasing"
    if t["n"] > 2:
        assert prizes[t["profit"] - 1] >= FLOOR_MULT * t["entry"], "floor"
        assert all(x == t["entry"] for x in prizes[t["profit"]:]), "break-even band"


def split_ties(prizes, ranks):
    """ranks: final rank per entry (1-based, ties share a rank). Returns payout per entry."""
    out = []
    for r in ranks:
        k = ranks.count(r)
        block = prizes[r - 1:r - 1 + k] + [0] * max(0, r - 1 + k - len(prizes))
        out.append(round(sum(block[:k]) / k, 2))
    return out


def settle_result_bet(stake, side, fills, outcome, commission=0.10):
    """fills: list of challenger amounts (opposite side). outcome: 'home'|'away'|'draw'."""
    matched = sum(fills)
    assert matched <= stake
    unmatched = stake - matched
    if outcome == "draw":
        return {"bettor": stake, "challengers": list(fills), "platform": 0}
    if outcome == side:
        profit = matched
        fee = round(profit * commission)
        return {"bettor": stake + profit - fee, "challengers": [0] * len(fills), "platform": fee}
    fees = [round(f * commission) for f in fills]
    return {"bettor": unmatched, "challengers": [2 * f - c for f, c in zip(fills, fees)],
            "platform": sum(fees)}


def settle_h2h(stake, creator_pts, taker_pts, commission=0.10):
    if creator_pts == taker_pts:
        return {"creator": stake, "taker": stake, "platform": 0}
    fee = round(stake * commission)
    win = 2 * stake - fee
    return ({"creator": win, "taker": 0, "platform": fee} if creator_pts > taker_pts
            else {"creator": 0, "taker": win, "platform": fee})


def rank_label(a, b):
    return str(a) if a == b else f"{a}–{b}"


def summarize(t, show=10):
    pr = t["prizes"]
    rows = [(str(i + 1), f"{pr[i]:,}") for i in range(min(show, t["profit"]))]
    if t["profit"] > show:
        rows.append((rank_label(show + 1, t["profit"]), f"{pr[t['profit'] - 1]:,}–{pr[show]:,}"))
    if t["paid"] > t["profit"]:
        rows.append((rank_label(t["profit"] + 1, t["paid"]), f"{t['entry']:,} (money back)"))
    return rows


if __name__ == "__main__":
    out = {"tables": {}, "p2p": {}}
    for n in (2, 5, 11, 100, 400, 1000):
        t = payout_table(n, 1000)
        check_table(t)
        out["tables"][str(n)] = {**{k: v for k, v in t.items() if k != "prizes"},
                                 "first": t["prizes"][0], "last_profit": t["prizes"][t["profit"] - 1],
                                 "summary": summarize(t)}
    # N400 "Mini ticket" contest offered on every match
    for n in (100, 1000):
        t = payout_table(n, 400)
        check_table(t)
        out["tables"][f"mini{n}"] = {**{k: v for k, v in t.items() if k != "prizes"},
                                     "first": t["prizes"][0], "last_profit": t["prizes"][t["profit"] - 1],
                                     "summary": summarize(t)}
    # tie example: 11-player contest, entries ranked 1,2,2,4
    t11 = payout_table(11, 1000)
    out["tie_example"] = {"prizes": t11["prizes"], "ranks": [1, 2, 2, 4],
                          "payouts": split_ties(t11["prizes"], [1, 2, 2, 4])}

    ex = {
        "home_wins": settle_result_bet(5000, "home", [1000, 1000, 1000], "home"),
        "away_wins": settle_result_bet(5000, "home", [1000, 1000, 1000], "away"),
        "draw": settle_result_bet(5000, "home", [1000, 1000, 1000], "draw"),
        "h2h_win": settle_h2h(1000, 182.5, 160),
        "h2h_tie": settle_h2h(1000, 150, 150),
    }
    assert ex["home_wins"]["bettor"] == 7700
    assert ex["away_wins"]["challengers"] == [1900, 1900, 1900] and ex["away_wins"]["bettor"] == 2000
    assert ex["draw"] == {"bettor": 5000, "challengers": [1000, 1000, 1000], "platform": 0}
    assert ex["h2h_win"] == {"creator": 1900, "taker": 0, "platform": 100}
    out["p2p"] = ex

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    for k, v in out["tables"].items():
        print(k, "pool", v["pool"], "paid", v["paid"], "profit", v["profit"], "alpha", v["alpha"],
              "1st", v["first"], "last profit", v["last_profit"])
    print("tie", out["tie_example"]["payouts"])
    print("p2p", json.dumps(ex))
    print("ALL CHECKS PASSED")
