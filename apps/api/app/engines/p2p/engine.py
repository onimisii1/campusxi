"""P2P settlement: Fantasy H2H challenges and Home/Away match-result bets (PRD 6.11–6.12).

Even money, 10% commission on the winner's profit, N1,000 minimum stake. Every
naira of liability is escrowed: matched challenger slices can never exceed the
bettor's stake. All money is integer kobo.
"""
from dataclasses import dataclass, field

KOBO = 100
COMMISSION_BPS = 1000
MIN_STAKE = 1000 * KOBO

FANTASY_H2H = "fantasy_h2h"
MATCH_RESULT = "match_result"
HOME, AWAY, DRAW = "home", "away", "draw"


@dataclass(frozen=True)
class Fill:
    challenger_id: str
    amount: int


@dataclass(frozen=True)
class Bet:
    kind: str
    creator_id: str
    stake: int
    creator_side: str | None = None          # match_result only
    fills: tuple = ()
    commission_bps: int = COMMISSION_BPS

    @property
    def matched(self) -> int:
        return sum(f.amount for f in self.fills)

    @property
    def unmatched(self) -> int:
        return self.stake - self.matched


@dataclass(frozen=True)
class Settlement:
    creator: int                              # paid back to the creator, kobo
    fills: tuple = field(default_factory=tuple)  # paid to each fill, same order as bet.fills
    platform: int = 0

    def total(self) -> int:
        return self.creator + sum(self.fills) + self.platform


def commission(profit: int, bps: int = COMMISSION_BPS) -> int:
    return profit * bps // 10000


def win_payout(amount: int, bps: int = COMMISSION_BPS) -> int:
    """What a winning slice of `amount` pays back: stake + equal profit - commission."""
    return 2 * amount - commission(amount, bps)


def opposite(side: str) -> str:
    if side not in (HOME, AWAY):
        raise ValueError("side must be home or away")
    return AWAY if side == HOME else HOME


def validate_new_bet(kind: str, stake: int, side: str | None = None,
                     result_bets_enabled: bool = False) -> list:
    errors = []
    if kind not in (FANTASY_H2H, MATCH_RESULT):
        errors.append(f"unknown bet kind {kind!r}")
    if kind == MATCH_RESULT:
        if not result_bets_enabled:
            errors.append("match-result bets are switched off until a sports-betting licence is held")
        if side not in (HOME, AWAY):
            errors.append("choose home or away")
    if kind == FANTASY_H2H and side is not None:
        errors.append("fantasy H2H challenges have no side")
    if stake < MIN_STAKE:
        errors.append("minimum stake is N1,000")
    return errors


def validate_fill(bet: Bet, challenger_id: str, amount: int, linked_ids=frozenset()) -> list:
    errors = []
    if challenger_id == bet.creator_id:
        errors.append("you can't accept your own bet")
    elif challenger_id in linked_ids:
        errors.append("linked accounts can't bet against each other")
    if bet.kind == FANTASY_H2H:
        if bet.fills:
            errors.append("this challenge already has a taker")
        if amount != bet.stake:
            errors.append("an H2H challenge is accepted for the full stake")
    else:
        if amount < MIN_STAKE:
            errors.append("minimum stake is N1,000")
        if amount > bet.unmatched:
            errors.append(f"only {bet.unmatched / KOBO:,.0f} naira is left to match")
    return errors


def add_fill(bet: Bet, challenger_id: str, amount: int, linked_ids=frozenset()) -> Bet:
    errors = validate_fill(bet, challenger_id, amount, linked_ids)
    if errors:
        raise ValueError("; ".join(errors))
    return Bet(bet.kind, bet.creator_id, bet.stake, bet.creator_side,
               bet.fills + (Fill(challenger_id, amount),), bet.commission_bps)


def quote_creator(stake: int, bps: int = COMMISSION_BPS) -> int:
    """Card text: 'Stake N5,000 -> win up to N9,500'."""
    return win_payout(stake, bps)


def quote_fill(bet: Bet, amount: int) -> dict:
    """What a challenger's slice pays in each outcome (shown before confirming)."""
    win = win_payout(amount, bet.commission_bps)
    if bet.kind == FANTASY_H2H:
        return {"side": None, "win": win, "lose": 0, "tie": amount}
    return {"side": opposite(bet.creator_side), "win": win, "lose": 0, "draw": amount}


def settle_result_bet(bet: Bet, outcome: str) -> Settlement:
    """Settle a Home/Away bet on the admin-confirmed result. A draw voids the bet."""
    if bet.kind != MATCH_RESULT:
        raise ValueError("not a match-result bet")
    if outcome not in (HOME, AWAY, DRAW):
        raise ValueError("outcome must be home, away or draw")
    if outcome == DRAW:
        s = Settlement(bet.stake, tuple(f.amount for f in bet.fills), 0)
    elif outcome == bet.creator_side:
        fee = commission(bet.matched, bet.commission_bps)
        s = Settlement(bet.stake + bet.matched - fee, tuple(0 for _ in bet.fills), fee)
    else:
        fees = [commission(f.amount, bet.commission_bps) for f in bet.fills]
        s = Settlement(bet.unmatched, tuple(2 * f.amount - c for f, c in zip(bet.fills, fees)), sum(fees))
    _check_conserved(bet, s)
    return s


def settle_h2h(bet: Bet, creator_points, taker_points) -> Settlement:
    if bet.kind != FANTASY_H2H:
        raise ValueError("not a fantasy H2H challenge")
    if not bet.fills:
        return refund(bet)
    if creator_points == taker_points:
        s = Settlement(bet.stake, (bet.stake,), 0)
    else:
        fee = commission(bet.stake, bet.commission_bps)
        win = 2 * bet.stake - fee
        s = (Settlement(win, (0,), fee) if creator_points > taker_points
             else Settlement(0, (win,), fee))
    _check_conserved(bet, s)
    return s


def refund(bet: Bet) -> Settlement:
    """Abandoned match or cancelled bet: everyone gets their stake back."""
    s = Settlement(bet.stake, tuple(f.amount for f in bet.fills), 0)
    _check_conserved(bet, s)
    return s


def _check_conserved(bet: Bet, s: Settlement):
    if s.total() != bet.stake + bet.matched:
        raise AssertionError("settlement does not conserve escrowed money")
