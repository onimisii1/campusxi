"""Contest payout engine (PRD 6.7–6.10). All money is integer kobo.

Confirmed rules: a flat 40% platform fee; the 60% prize pool pays the top 40% of
ranks, the top 25% in profit (each at least 1.2x entry), the rest their entry back.
The engine builds the prize table for the actual number of entries at lock.
"""
import math
from dataclasses import dataclass

KOBO = 100
PLATFORM_FEE_BPS = 4000
PAID_SHARE_BPS = 4000
PROFIT_SHARE_BPS = 2500
FLOOR_NUM, FLOOR_DEN = 12, 10        # profit ranks get at least 1.2x entry
ROUND_UNIT = 10 * KOBO               # prizes rounded down to N10; residue to 1st
MAX_ENTRANTS = 1000
MINI_ENTRY = 400 * KOBO
STANDARD_MIN_ENTRY = 1000 * KOBO
ENTRY_TIERS = (MINI_ENTRY, 1000 * KOBO, 2000 * KOBO, 5000 * KOBO, 10000 * KOBO)


@dataclass(frozen=True)
class PayoutTable:
    n: int
    entry: int
    fee_bps: int
    gross: int
    pool: int
    paid: int
    profit: int
    prizes: tuple          # prizes[i] is the prize for rank i + 1, in kobo

    @property
    def platform_fee(self) -> int:
        return self.gross - self.pool


def first_share_bps_for(n: int) -> int | None:
    """Target share of the pool for 1st prize, by contest size tier (PRD 6.7)."""
    if n <= 2:
        return None
    if n <= 20:
        return 5000
    if n <= 200:
        return 2500
    return 1500


def bands(n: int) -> tuple:
    """(paid ranks, profit ranks) for n entries."""
    if n < 2:
        raise ValueError("a contest needs at least 2 entries")
    if n == 2:
        return 1, 1
    profit = max(1, n * PROFIT_SHARE_BPS // 10000)
    paid = max(profit, n * PAID_SHARE_BPS // 10000)
    return paid, profit


def prize_pool(n: int, entry: int, fee_bps: int = PLATFORM_FEE_BPS) -> int:
    return n * entry * (10000 - fee_bps) // 10000


def profit_floor(entry: int) -> int:
    return -(-entry * FLOOR_NUM // FLOOR_DEN)


def is_fundable(n: int, entry: int, fee_bps: int = PLATFORM_FEE_BPS) -> bool:
    if n == 2:
        return True
    paid, profit = bands(n)
    pool = prize_pool(n, entry, fee_bps)
    return pool - (paid - profit) * entry - profit * profit_floor(entry) >= 0


def payout_table(n: int, entry: int, fee_bps: int = PLATFORM_FEE_BPS,
                 first_share_bps: int | None = None) -> PayoutTable:
    if not 2 <= n <= MAX_ENTRANTS:
        raise ValueError(f"entries must be between 2 and {MAX_ENTRANTS} (got {n})")
    if entry <= 0:
        raise ValueError("entry fee must be positive for a paid contest")
    gross = n * entry
    pool = prize_pool(n, entry, fee_bps)
    if n == 2:
        return PayoutTable(n, entry, fee_bps, gross, pool, 1, 1, (pool,))
    if not is_fundable(n, entry, fee_bps):
        raise ValueError(f"a {fee_bps / 100:g}% fee cannot fund the payout bands for {n} entries")

    paid, profit = bands(n)
    remainder = pool - (paid - profit) * entry
    floor_each = profit_floor(entry)
    extra = remainder - profit * floor_each
    share = first_share_bps if first_share_bps is not None else first_share_bps_for(n)
    alpha = _solve_alpha(profit, floor_each, extra, share * pool / 10000)

    weights = [1 / (i ** alpha) for i in range(1, profit + 1)]
    total_w = sum(weights)
    top = [max(floor_each, math.floor((floor_each + extra * w / total_w) / ROUND_UNIT) * ROUND_UNIT)
           for w in weights]
    top[0] += remainder - sum(top)
    prizes = tuple(top) + (entry,) * (paid - profit)
    return PayoutTable(n, entry, fee_bps, gross, pool, paid, profit, prizes)


def _solve_alpha(profit: int, floor_each: int, extra: int, target_first: float) -> float:
    """Find the decay exponent that gives 1st prize ~= target_first."""
    def first_for(alpha):
        weights = [1 / (i ** alpha) for i in range(1, profit + 1)]
        return floor_each + extra * weights[0] / sum(weights)

    if first_for(0.0) >= target_first:
        return 0.0
    if first_for(20.0) <= target_first:
        return 20.0
    lo, hi = 0.0, 20.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if first_for(mid) < target_first:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def min_fill(capacity: int) -> int:
    """Entries needed at lock for a contest to run (PRD 6.7)."""
    return max(math.ceil(capacity * 0.2), 10 if capacity >= 11 else 2)


def should_run(entries: int, capacity: int, guaranteed: bool = False) -> bool:
    return guaranteed or entries >= min_fill(capacity)


def validate_contest(capacity: int, entry: int, fee_bps: int = PLATFORM_FEE_BPS) -> list:
    """Errors for a contest template; checks every entry count it could lock with."""
    errors = []
    if not 2 <= capacity <= MAX_ENTRANTS:
        errors.append(f"capacity must be 2 to {MAX_ENTRANTS}")
    if entry != MINI_ENTRY and entry < STANDARD_MIN_ENTRY:
        errors.append("paid entry must be the N400 Mini ticket or at least N1,000")
    if entry % (10 * KOBO):
        errors.append("entry fee must be a whole multiple of N10")
    if not errors:
        bad = [n for n in range(min(min_fill(capacity), capacity), capacity + 1)
               if not is_fundable(n, entry, fee_bps)]
        if bad:
            errors.append(f"fee cannot fund payouts for {bad[0]} entries")
    return errors


def settle_contest(entries, table: PayoutTable) -> dict:
    """entries: [(entry_id, points)] in join order. Returns {entry_id: payout_kobo}.

    Ties share the combined prizes of the ranks they occupy equally; leftover kobo
    from the split go one each to the earliest-joined tied entries.
    """
    if len(entries) != table.n:
        raise ValueError(f"table is for {table.n} entries, got {len(entries)}")
    order = sorted(range(len(entries)), key=lambda i: (-entries[i][1], i))
    payouts = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and entries[order[j + 1]][1] == entries[order[i]][1]:
            j += 1
        group = order[i:j + 1]
        pot = sum(table.prizes[k] for k in range(i, j + 1) if k < len(table.prizes))
        each, left = divmod(pot, len(group))
        for rank_pos, idx in enumerate(sorted(group)):
            payouts[entries[idx][0]] = each + (1 if rank_pos < left else 0)
        i = j + 1
    return payouts


def final_ranks(entries) -> dict:
    """Competition ranking (1, 2, 2, 4) by points, highest first."""
    pts = sorted((p for _, p in entries), reverse=True)
    return {eid: pts.index(p) + 1 for eid, p in entries}
