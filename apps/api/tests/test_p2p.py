"""P2P golden tests: the PRD 6.11–6.12 worked examples plus escrow rules."""
import pytest

from app.engines.p2p import (
    AWAY, DRAW, FANTASY_H2H, HOME, MATCH_RESULT, Bet, add_fill, quote_creator, quote_fill,
    refund, settle_h2h, settle_result_bet, validate_fill, validate_new_bet,
)

K = 100  # kobo per naira


def result_bet():
    """Bettor stakes N5,000 on Home; three challengers take N1,000 each on Away."""
    bet = Bet(MATCH_RESULT, "bettor", 5000 * K, HOME)
    for c in ("c1", "c2", "c3"):
        bet = add_fill(bet, c, 1000 * K)
    return bet


def test_card_quotes():
    assert quote_creator(5000 * K) == 9500 * K
    q = quote_fill(Bet(MATCH_RESULT, "b", 5000 * K, HOME), 1000 * K)
    assert q == {"side": AWAY, "win": 1900 * K, "lose": 0, "draw": 1000 * K}


def test_home_wins_bettor_takes_all_matched():
    s = settle_result_bet(result_bet(), HOME)
    assert s.creator == 7700 * K and s.fills == (0, 0, 0) and s.platform == 300 * K


def test_away_wins_each_challenger_paid_bettor_gets_unmatched():
    s = settle_result_bet(result_bet(), AWAY)
    assert s.creator == 2000 * K and s.fills == (1900 * K,) * 3 and s.platform == 300 * K


def test_draw_voids_everything():
    s = settle_result_bet(result_bet(), DRAW)
    assert s.creator == 5000 * K and s.fills == (1000 * K,) * 3 and s.platform == 0


def test_unmatched_bet_returns_stake_whatever_the_result():
    bet = Bet(MATCH_RESULT, "b", 2000 * K, AWAY)
    for outcome in (HOME, AWAY, DRAW):
        assert settle_result_bet(bet, outcome).creator == 2000 * K


def test_fills_can_never_exceed_stake():
    bet = result_bet()
    assert bet.unmatched == 2000 * K
    assert any("left to match" in e for e in validate_fill(bet, "c4", 2500 * K))
    bet = add_fill(bet, "c4", 2000 * K)
    assert bet.unmatched == 0
    assert any("left to match" in e for e in validate_fill(bet, "c5", 1000 * K))


def test_fill_rules():
    bet = Bet(MATCH_RESULT, "b", 5000 * K, HOME)
    assert "you can't accept your own bet" in validate_fill(bet, "b", 1000 * K)
    assert "linked accounts can't bet against each other" in validate_fill(bet, "alt", 1000 * K, {"alt"})
    assert "minimum stake is N1,000" in validate_fill(bet, "c", 400 * K)
    with pytest.raises(ValueError):
        add_fill(bet, "b", 1000 * K)


def test_new_bet_rules():
    assert validate_new_bet(FANTASY_H2H, 1000 * K) == []
    assert "minimum stake is N1,000" in validate_new_bet(FANTASY_H2H, 400 * K)
    off = validate_new_bet(MATCH_RESULT, 1000 * K, HOME)
    assert any("switched off" in e for e in off)
    assert validate_new_bet(MATCH_RESULT, 1000 * K, HOME, result_bets_enabled=True) == []
    assert "choose home or away" in validate_new_bet(MATCH_RESULT, 1000 * K, DRAW, result_bets_enabled=True)


def test_h2h_settlement():
    bet = add_fill(Bet(FANTASY_H2H, "creator", 1000 * K), "taker", 1000 * K)
    win = settle_h2h(bet, 182.5, 160)
    assert (win.creator, win.fills, win.platform) == (1900 * K, (0,), 100 * K)
    lose = settle_h2h(bet, 100, 160)
    assert (lose.creator, lose.fills) == (0, (1900 * K,))
    tie = settle_h2h(bet, 150, 150)
    assert (tie.creator, tie.fills, tie.platform) == (1000 * K, (1000 * K,), 0)


def test_h2h_needs_exactly_one_full_taker():
    bet = Bet(FANTASY_H2H, "creator", 1000 * K)
    assert "an H2H challenge is accepted for the full stake" in validate_fill(bet, "t", 500 * K)
    bet = add_fill(bet, "t", 1000 * K)
    assert "this challenge already has a taker" in validate_fill(bet, "t2", 1000 * K)


def test_unaccepted_h2h_and_abandoned_match_refund():
    assert settle_h2h(Bet(FANTASY_H2H, "c", 1000 * K), 10, 0).creator == 1000 * K
    s = refund(result_bet())
    assert s.creator == 5000 * K and s.fills == (1000 * K,) * 3 and s.platform == 0
