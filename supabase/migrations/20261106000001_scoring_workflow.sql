-- Phase 3: scorer workflow (PRD 5.5, 5.11).
--
-- Each match has a primary scorer (whose stream drives live points) and an optional
-- secondary scorer recording independently. On confirmation the admin names the
-- official stream; fantasy points are always computed from that stream.

alter table match_scorers
  add column role text not null default 'primary' check (role in ('primary', 'secondary'));
create unique index match_scorers_one_per_role on match_scorers (match_id, role);

-- What each scorer reported as the final score when submitting.
alter table stat_submissions
  add column home_score int check (home_score >= 0),
  add column away_score int check (away_score >= 0),
  add column shootout_winner text check (shootout_winner in ('home', 'away'));

alter table match_results
  add column official_scorer_id uuid references users(id),
  add constraint match_results_shootout_only_on_draw
    check (shootout_winner is null or winner = 'draw');

-- Postponements keep their history: the original start is preserved here.
alter table matches
  add column original_start timestamptz;
