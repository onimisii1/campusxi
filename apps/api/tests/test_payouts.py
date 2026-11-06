"""Payout engine golden tests: every table in PRD 6.9 plus invariants."""
import pytest

from app.engines.payouts import (
    ENTRY_TIERS, KOBO, MINI_ENTRY, bands, final_ranks, min_fill, payout_table,
    settle_contest, should_run, validate_contest,
)

N1000 = 1000 * KOBO


def naira(prizes):
    return [p // KOBO for p in prizes]


# (n, entry, pool, paid, profit, first, lowest profit) from PRD 6.9 at the confirmed 40% fee
GOLDEN = [
    (2, N1000, 1_200, 1, 1, 1_200, 1_200),
    (5, N1000, 3_000, 2, 1, 2_000, 2_000),
    (11, N1000, 6_600, 4, 2, 3_300, 1_300),
    (100, N1000, 60_000, 40, 25, 15_040, 1_200),
    (400, N1000, 240_000, 160, 100, 36_540, 1_200),
    (1000, N1000, 600_000, 400, 250, 91_110, 1_200),
    (100, MINI_ENTRY, 24_000, 40, 25, 6_030, 480),
    (1000, MINI_ENTRY, 240_000, 400, 250, 36_800, 480),
]


@pytest.mark.parametrize("n,entry,pool,paid,profit,first,low", GOLDEN)
def test_golden_tables(n, entry, pool, paid, profit, first, low):
    t = payout_table(n, entry)
    assert t.pool == pool * KOBO
    assert (t.paid, t.profit) == (paid, profit)
    assert t.prizes[0] == first * KOBO
    assert t.prizes[profit - 1] == low * KOBO
    assert t.platform_fee == n * entry * 40 // 100


def test_golden_top_ten_1000_entries():
    t = payout_table(1000, N1000)
    assert naira(t.prizes[:10]) == [91_110, 24_180, 11_620, 7_150, 5_050, 3_890, 3_190, 2_740, 2_420, 2_190]
    assert naira(t.prizes[249:251]) == [1_200, 1_000]
    assert naira(t.prizes[10:11]) == [2_020]


def test_golden_top_ten_mini():
    t = payout_table(1000, MINI_ENTRY)
    assert naira(t.prizes[:10]) == [36_800, 9_670, 4_650, 2_860, 2_020, 1_550, 1_270, 1_090, 960, 870]


def test_small_contests_match_fantasyfi_shapes():
    assert bands(5) == (2, 1)      # FantasyFi 5 spots -> 2 ranks paid
    assert bands(11) == (4, 2)     # FantasyFi 11 spots -> 4 ranks ("win up to 40% rank")
    assert naira(payout_table(5, N1000).prizes) == [2_000, 1_000]


SAMPLE_NS = sorted({2, 3, 4, 5, 6, 7, 10, 11, 19, 20, 21, 50, 99, 100, 199, 200, 201, 333, 500, 777, 999, 1000})


@pytest.mark.parametrize("entry", ENTRY_TIERS)
@pytest.mark.parametrize("n", SAMPLE_NS)
def test_invariants(n, entry):
    t = payout_table(n, entry)
    p = t.prizes
    assert sum(p) == t.pool, "prizes must sum to the pool exactly"
    assert all(a >= b for a, b in zip(p, p[1:])), "prizes never increase down the ranks"
    assert all(isinstance(x, int) for x in p), "money is integer kobo"
    if n > 2:
        assert p[t.profit - 1] * 10 >= entry * 12, "every profit rank wins at least 1.2x entry"
        assert all(x == entry for x in p[t.profit:]), "break-even band gets exactly the entry back"
        assert all(x % (10 * KOBO) == 0 for x in p[1:t.profit]), "prizes rounded to N10"
    assert t.paid == len(p)


def test_late_entries_grow_the_pool_but_pay_by_the_same_table():
    """Late joiners pay 150% (agreed 6 Nov 2026); the pool grows, the bands don't change."""
    on_time = payout_table(10, N1000)
    with_late = payout_table(10, N1000, gross=8 * N1000 + 2 * 1500 * KOBO)
    assert with_late.gross == 11_000 * KOBO and with_late.pool == 6_600 * KOBO
    assert sum(with_late.prizes) == with_late.pool
    assert (with_late.paid, with_late.profit) == (on_time.paid, on_time.profit)
    assert all(x == N1000 for x in with_late.prizes[with_late.profit:])     # money back is the base entry
    assert all(a >= b for a, b in zip(with_late.prizes, on_time.prizes))   # nobody is worse off
    with pytest.raises(ValueError, match="can't be less"):
        payout_table(10, N1000, gross=9 * N1000)


def test_rejects_out_of_range():
    with pytest.raises(ValueError):
        payout_table(1, N1000)
    with pytest.raises(ValueError):
        payout_table(1001, N1000)
    with pytest.raises(ValueError, match="cannot fund"):
        payout_table(100, N1000, fee_bps=6000)


def test_ties_share_prizes():
    # PRD 6.10: 11-entry table 3,300 / 1,300 / 1,000 / 1,000; two tie for 2nd
    t = payout_table(11, N1000)
    entries = [("a", 90), ("b", 70), ("c", 70), ("d", 60)] + [(f"x{i}", 10 - i) for i in range(7)]
    pay = settle_contest(entries, t)
    assert pay["a"] == 3_300 * KOBO
    assert pay["b"] == pay["c"] == 1_150 * KOBO
    assert pay["d"] == 1_000 * KOBO
    assert sum(pay.values()) == t.pool
    assert final_ranks(entries)["d"] == 4


def test_tie_split_leftover_kobo_goes_to_earliest_entry():
    t = payout_table(11, N1000)
    entries = [(f"e{i}", 50) for i in range(3)] + [(f"x{i}", 1) for i in range(8)]
    pay = settle_contest(entries, t)
    pot = sum(t.prizes[:3])
    assert sorted(pay[f"e{i}"] for i in range(3)) == sorted([pot // 3 + (1 if i < pot % 3 else 0) for i in range(3)])
    assert sum(pay.values()) == t.pool


def test_everyone_tied_gets_equal_share():
    t = payout_table(10, N1000)
    pay = settle_contest([(f"e{i}", 100) for i in range(10)], t)
    assert sum(pay.values()) == t.pool
    assert max(pay.values()) - min(pay.values()) <= 1


def test_min_fill_and_cancellation():
    assert min_fill(2) == 2
    assert min_fill(5) == 2
    assert min_fill(11) == 10
    assert min_fill(1000) == 200
    assert not should_run(199, 1000)
    assert should_run(200, 1000)
    assert should_run(3, 1000, guaranteed=True)


def test_contest_template_validation():
    assert validate_contest(1000, N1000) == []
    assert validate_contest(1000, MINI_ENTRY) == []
    assert any("Mini ticket" in e for e in validate_contest(100, 500 * KOBO))
    assert any("capacity" in e for e in validate_contest(1001, N1000))
    assert any("cannot fund" in e for e in validate_contest(100, N1000, fee_bps=6000))
