-- Phase 4: free pilot (PRD 10, Phase 4). Free contests with sponsor prize text, a
-- season leaderboard, and free "bragging rights" fantasy H2H challenges.

alter table contests
  add column name text not null default 'Free contest' check (length(name) between 2 and 60),
  add column prize_text text check (length(prize_text) <= 200);

-- Free challenges have a zero stake; anything paid still starts at N1,000.
alter table p2p_bets drop constraint p2p_bets_stake_kobo_check;
alter table p2p_bets add constraint p2p_bets_stake_kobo_check
  check ((kind = 'fantasy_h2h' and stake_kobo = 0) or stake_kobo >= 100000);

alter table p2p_bet_fills drop constraint p2p_bet_fills_amount_kobo_check;
alter table p2p_bet_fills add constraint p2p_bet_fills_amount_kobo_check check (amount_kobo >= 0);

-- Recorded when the result is confirmed.
alter table p2p_bets
  add column creator_points numeric(10, 2),
  add column taker_points numeric(10, 2),
  add column outcome text check (outcome in ('creator', 'taker', 'tie')),
  add column settled_at timestamptz;

create index fantasy_teams_match on fantasy_teams (match_id);
create index p2p_bets_creator on p2p_bets (creator_id);
create index p2p_bet_fills_challenger on p2p_bet_fills (challenger_id);
