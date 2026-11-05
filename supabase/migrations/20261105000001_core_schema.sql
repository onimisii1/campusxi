-- CampusXI core schema (PRD section 7).
--
-- Money is integer kobo (bigint). stat_events, p2p_bet_events, wallet_ledger and
-- audit_log are append-only: triggers below reject UPDATE, DELETE and TRUNCATE.
-- Row Level Security is enabled on every table with no policies, so Supabase's
-- anon/authenticated roles cannot touch them; only the API (table owner) can.
-- Realtime read policies arrive with the fan app (Phase 4).

-- ---------- append-only guard ----------

create function forbid_mutation() returns trigger
language plpgsql as $$
begin
  raise exception '% is append-only: % is not allowed', tg_table_name, tg_op
    using errcode = 'restrict_violation';
end;
$$;

-- ---------- tenancy and competition structure ----------

create table schools (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  created_at timestamptz not null default now()
);

create table sports (
  code text primary key,
  name text not null,
  live boolean not null default false,
  sort_order int not null default 0
);

insert into sports (code, name, live, sort_order) values
  ('football', 'Football', true, 1),
  ('basketball', 'Basketball', true, 2),
  ('volleyball', 'Volleyball', true, 3),
  ('table_tennis', 'Table tennis', false, 4),
  ('athletics', 'Athletics', false, 5),
  ('handball', 'Handball', false, 6);

-- id is the Supabase auth user id (auth.users.id).
create table users (
  id uuid primary key,
  school_id uuid not null references schools(id),
  team_name text not null check (length(team_name) between 3 and 30),
  roles text[] not null default '{player}'
    check (roles <@ array['player', 'scorer', 'admin', 'superadmin']),
  kyc_status text not null default 'none'
    check (kyc_status in ('none', 'pending', 'verified', 'rejected')),
  dob date not null,
  device_fingerprint text,
  self_excluded_until timestamptz,
  created_at timestamptz not null default now(),
  -- The whole platform is 18+ (PRD 11.2).
  constraint users_18_plus check (dob <= (created_at::date - interval '18 years'))
);
-- Team names are permanent and unique regardless of case (PRD A1).
create unique index users_team_name_ci on users (lower(team_name));

create table kyc_records (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  provider text not null,
  provider_ref text not null,
  verified_name text,
  dob date,
  status text not null check (status in ('pending', 'verified', 'rejected')),
  created_at timestamptz not null default now()
);

create table tournaments (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references schools(id),
  sport text not null references sports(code),
  name text not null,
  match_minutes int not null check (match_minutes between 0 and 200),
  starts_on date,
  ends_on date,
  status text not null default 'draft' check (status in ('draft', 'published', 'completed')),
  created_at timestamptz not null default now(),
  unique (school_id, name)
);

create table teams (
  id uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references tournaments(id),
  name text not null,
  created_at timestamptz not null default now(),
  unique (tournament_id, name)
);

create table athletes (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references teams(id),
  display_name text not null,
  position text not null,
  -- Set when the athlete also has a player account; athletes may play fully.
  user_id uuid references users(id),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (team_id, display_name)
);

create table matches (
  id uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references tournaments(id),
  home_team_id uuid not null references teams(id),
  away_team_id uuid not null references teams(id),
  venue text,
  scheduled_start timestamptz not null,   -- lock time for teams, contests and bets
  scheduled_minutes int not null,
  rules_version text not null,            -- scoring rules pinned for this match
  status text not null default 'scheduled' check (status in
    ('scheduled', 'lineup_out', 'live', 'final_pending', 'confirmed', 'abandoned', 'postponed')),
  created_at timestamptz not null default now(),
  check (home_team_id <> away_team_id)
);
create index matches_tournament_start on matches (tournament_id, scheduled_start);
create index matches_status_start on matches (status, scheduled_start);

create table match_scorers (
  match_id uuid not null references matches(id),
  user_id uuid not null references users(id),
  assigned_at timestamptz not null default now(),
  primary key (match_id, user_id)
);

create table match_lineups (
  match_id uuid not null references matches(id),
  athlete_id uuid not null references athletes(id),
  started boolean not null,
  published_at timestamptz not null default now(),
  primary key (match_id, athlete_id)
);

create table match_results (
  match_id uuid primary key references matches(id),
  home_score int not null check (home_score >= 0),
  away_score int not null check (away_score >= 0),
  winner text not null check (winner in ('home', 'away', 'draw')),
  shootout_winner text check (shootout_winner in ('home', 'away')),
  confirmed_by uuid not null references users(id),
  confirmed_at timestamptz not null default now()
);

-- ---------- stats (append-only) ----------

create table stat_events (
  id bigserial primary key,
  match_id uuid not null references matches(id),
  scorer_id uuid not null references users(id),
  athlete_id uuid not null references athletes(id),
  event_type text not null,
  minute int check (minute >= 0),
  amount int not null default 1 check (amount > 0),
  reverses_event_id bigint references stat_events(id),
  client_seq int not null,                -- ordering from the scorer's device (offline sync)
  created_at timestamptz not null default now(),
  unique (match_id, scorer_id, client_seq)
);
create index stat_events_match on stat_events (match_id, scorer_id, client_seq);
create trigger stat_events_append_only before update or delete on stat_events
  for each row execute function forbid_mutation();
create trigger stat_events_no_truncate before truncate on stat_events
  for each statement execute function forbid_mutation();

create table stat_submissions (
  id uuid primary key default gen_random_uuid(),
  match_id uuid not null references matches(id),
  scorer_id uuid not null references users(id),
  submitted_at timestamptz not null default now(),
  unique (match_id, scorer_id)
);

-- ---------- fantasy teams ----------

create table fantasy_teams (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  match_id uuid not null references matches(id),
  label text not null,
  locked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, match_id, label)
);
create index fantasy_teams_user_match on fantasy_teams (user_id, match_id);

create table fantasy_team_picks (
  fantasy_team_id uuid not null references fantasy_teams(id) on delete cascade,
  athlete_id uuid not null references athletes(id),
  role text not null default 'none' check (role in ('none', 'captain', 'vice_captain', 'key')),
  primary key (fantasy_team_id, athlete_id)
);

-- ---------- contests ----------

create table contests (
  id uuid primary key default gen_random_uuid(),
  match_id uuid not null references matches(id),
  capacity int not null check (capacity between 2 and 1000),
  entry_fee_kobo bigint not null check (entry_fee_kobo >= 0),
  rake_bps int not null default 4000 check (rake_bps between 0 and 9000),
  min_fill int not null check (min_fill >= 2),
  guaranteed boolean not null default false,
  team_cap int not null default 10 check (team_cap between 1 and 10),
  first_share_bps int check (first_share_bps between 0 and 10000),
  is_mini boolean not null default false,
  status text not null default 'open' check (status in ('open', 'locked', 'cancelled', 'settled')),
  created_at timestamptz not null default now(),
  check (min_fill <= capacity),
  check (not is_mini or entry_fee_kobo = 40000)
);
create index contests_match on contests (match_id);

create table payout_tables (
  contest_id uuid not null references contests(id),
  rank int not null check (rank >= 1),
  prize_kobo bigint not null check (prize_kobo > 0),
  primary key (contest_id, rank)
);

create table contest_entries (
  id uuid primary key default gen_random_uuid(),
  contest_id uuid not null references contests(id),
  fantasy_team_id uuid not null references fantasy_teams(id),
  user_id uuid not null references users(id),
  joined_at timestamptz not null default now(),
  final_points numeric(10, 2),
  final_rank int,
  payout_kobo bigint,
  unique (contest_id, fantasy_team_id)
);
create index contest_entries_contest on contest_entries (contest_id);

-- ---------- P2P bets ----------

create table p2p_bets (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('fantasy_h2h', 'match_result')),
  match_id uuid not null references matches(id),
  creator_id uuid not null references users(id),
  creator_side text check (creator_side in ('home', 'away')),
  creator_fantasy_team_id uuid references fantasy_teams(id),
  stake_kobo bigint not null check (stake_kobo >= 100000),
  matched_kobo bigint not null default 0,
  visibility text not null check (visibility in ('board', 'direct')),
  invite_token text unique,
  invitee_id uuid references users(id),
  commission_bps int not null default 1000 check (commission_bps between 0 and 5000),
  status text not null default 'open' check (status in
    ('open', 'partially_matched', 'matched', 'locked', 'settled', 'void', 'refunded', 'cancelled')),
  created_at timestamptz not null default now(),
  check (matched_kobo between 0 and stake_kobo),
  check ((kind = 'match_result' and creator_side is not null and creator_fantasy_team_id is null)
      or (kind = 'fantasy_h2h' and creator_side is null and creator_fantasy_team_id is not null))
);
create index p2p_bets_board on p2p_bets (match_id, status);

create table p2p_bet_fills (
  id uuid primary key default gen_random_uuid(),
  bet_id uuid not null references p2p_bets(id),
  challenger_id uuid not null references users(id),
  side text check (side in ('home', 'away')),
  challenger_fantasy_team_id uuid references fantasy_teams(id),
  amount_kobo bigint not null check (amount_kobo > 0),
  payout_kobo bigint,
  commission_kobo bigint,
  created_at timestamptz not null default now()
);
create index p2p_bet_fills_bet on p2p_bet_fills (bet_id);

create table p2p_bet_events (
  id bigserial primary key,
  bet_id uuid not null references p2p_bets(id),
  from_status text,
  to_status text not null,
  actor text not null,
  reason text,
  created_at timestamptz not null default now()
);
create trigger p2p_bet_events_append_only before update or delete on p2p_bet_events
  for each row execute function forbid_mutation();
create trigger p2p_bet_events_no_truncate before truncate on p2p_bet_events
  for each statement execute function forbid_mutation();

-- ---------- wallet (append-only, double-entry) ----------

create table wallet_ledger (
  id bigserial primary key,
  txn_id uuid not null,
  account text not null,          -- user:{id}:available, user:{id}:held, platform:rake, psp:clearing ...
  amount_kobo bigint not null check (amount_kobo <> 0),   -- credit > 0, debit < 0
  entry_type text not null check (entry_type in ('deposit', 'withdrawal', 'hold', 'release', 'entry_fee',
    'prize', 'stake', 'payout', 'refund', 'rake', 'commission', 'bonus')),
  ref_type text,
  ref_id uuid,
  created_at timestamptz not null default now()
);
create index wallet_ledger_account on wallet_ledger (account);
create index wallet_ledger_txn on wallet_ledger (txn_id);
create trigger wallet_ledger_append_only before update or delete on wallet_ledger
  for each row execute function forbid_mutation();
create trigger wallet_ledger_no_truncate before truncate on wallet_ledger
  for each statement execute function forbid_mutation();

-- Every transaction's lines must sum to zero, checked at commit.
create function wallet_txn_balanced() returns trigger
language plpgsql as $$
declare
  total bigint;
begin
  select coalesce(sum(amount_kobo), 0) into total from wallet_ledger where txn_id = new.txn_id;
  if total <> 0 then
    raise exception 'wallet transaction % does not balance (sum %)', new.txn_id, total
      using errcode = 'check_violation';
  end if;
  return null;
end;
$$;
create constraint trigger wallet_ledger_balanced after insert on wallet_ledger
  deferrable initially deferred for each row execute function wallet_txn_balanced();

create table deposits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  amount_kobo bigint not null check (amount_kobo > 0),
  psp text not null,
  psp_reference text not null unique,
  status text not null default 'pending' check (status in ('pending', 'success', 'failed')),
  webhook_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table withdrawals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  amount_kobo bigint not null check (amount_kobo > 0),
  psp_reference text unique,
  status text not null default 'pending' check (status in ('pending', 'paid', 'failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table referrals (
  id uuid primary key default gen_random_uuid(),
  referrer_id uuid not null references users(id),
  referred_id uuid not null unique references users(id),
  bonus_kobo bigint,
  credited_at timestamptz,
  created_at timestamptz not null default now(),
  check (referrer_id <> referred_id)
);

create table exclusions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  kind text not null check (kind in ('self_exclusion', 'deposit_limit', 'stake_limit')),
  value_kobo bigint,
  until timestamptz,
  created_at timestamptz not null default now()
);

-- ---------- audit (append-only) ----------

create table audit_log (
  id bigserial primary key,
  actor_id uuid references users(id),
  action text not null,
  target_type text,
  target_id uuid,
  details jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create trigger audit_log_append_only before update or delete on audit_log
  for each row execute function forbid_mutation();
create trigger audit_log_no_truncate before truncate on audit_log
  for each statement execute function forbid_mutation();

-- ---------- lock everything down from Supabase's public API ----------

do $$
declare
  t text;
begin
  foreach t in array array['schools', 'sports', 'users', 'kyc_records', 'tournaments', 'teams', 'athletes',
    'matches', 'match_scorers', 'match_lineups', 'match_results', 'stat_events', 'stat_submissions',
    'fantasy_teams', 'fantasy_team_picks', 'contests', 'payout_tables', 'contest_entries', 'p2p_bets',
    'p2p_bet_fills', 'p2p_bet_events', 'wallet_ledger', 'deposits', 'withdrawals', 'referrals',
    'exclusions', 'audit_log']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end;
$$;
