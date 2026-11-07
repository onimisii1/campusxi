-- Swipe to match (Nov 2026): open challenges shown one card at a time. Swiping left skips a card so it
-- doesn't come back; swiping right takes the challenge (an ordinary p2p_bet_fills row). A skip is a
-- per-player preference, not a money record: it can be undone (rewind) or cleared.
create table p2p_bet_skips (
  user_id uuid not null references users(id),
  bet_id uuid not null references p2p_bets(id),
  created_at timestamptz not null default now(),
  primary key (user_id, bet_id)
);
alter table p2p_bet_skips enable row level security;
