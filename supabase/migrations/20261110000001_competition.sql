-- Running a whole competition (NUESA 2026/27): match codes and stages, actual kick-off time,
-- walkovers, and results imported from before the app was used.

alter table matches
  -- The organisers' match code (M4, G5, SF1); unique within a tournament when set.
  add column code text check (code is null or length(code) between 1 and 12),
  add column stage text not null default 'league'
    check (stage in ('league', 'semi', 'final', 'third_place')),
  -- When the match actually started ("Kick off now" by an admin or the match's scorer).
  -- The match clock runs from here; teams still lock at scheduled_start.
  add column kicked_off_at timestamptz;
create unique index matches_tournament_code on matches (tournament_id, lower(code)) where code is not null;

alter table match_results
  -- A walkover counts in the league table, but nobody played, so fantasy is void.
  add column walkover boolean not null default false,
  -- Results entered after the fact (no scorer streams, no contests).
  add column imported boolean not null default false;
