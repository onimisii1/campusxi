-- Real money (Phase 5): wallet holds, payment events, bank accounts, idempotency, KYC, referrals.
--
-- Ledger accounts (wallet_ledger.account):
--   user:{id}:cash         withdrawable money
--   user:{id}:bonus        referral coins: stake-only, never withdrawn
--   user:{id}:held_cash    cash held for an entry, stake or withdrawal
--   user:{id}:held_bonus   coins held for an entry or stake
--   contest:{id}:pot       entry fees captured at settlement, paid out as prizes and fee
--   bet:{id}:pot           stakes captured at settlement
--   platform:fee           platform's 40% contest fee and 10% P2P commission
--   platform:bonus_pool    funds referral coins (goes negative as coins are issued)
--   psp:{provider}:clearing  money in transit with Paystack / Flutterwave

alter table wallet_ledger drop constraint wallet_ledger_entry_type_check;
alter table wallet_ledger add constraint wallet_ledger_entry_type_check check (entry_type in (
  'deposit', 'withdrawal', 'withdrawal_reversal', 'hold', 'release', 'entry_fee', 'prize', 'stake',
  'payout', 'refund', 'rake', 'commission', 'bonus', 'bonus_expiry'));

-- A hold ties held money to what it is for, with the cash/coin split so it can be returned
-- to the same place. Status only moves forward: held -> released | captured.
create table wallet_holds (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  ref_type text not null check (ref_type in ('contest_entry', 'bet', 'bet_fill', 'withdrawal')),
  ref_id uuid not null,
  cash_kobo bigint not null check (cash_kobo >= 0),
  bonus_kobo bigint not null check (bonus_kobo >= 0),
  status text not null default 'held' check (status in ('held', 'released', 'captured')),
  created_at timestamptz not null default now(),
  closed_at timestamptz,
  check (cash_kobo + bonus_kobo > 0)
);
create unique index wallet_holds_one_open on wallet_holds (ref_type, ref_id) where status = 'held';
create index wallet_holds_user on wallet_holds (user_id, created_at);

-- Every webhook we accept, verbatim; a second delivery of the same event is ignored.
create table payment_events (
  id bigserial primary key,
  provider text not null check (provider in ('paystack', 'flutterwave')),
  event_id text not null,
  event_type text not null,
  payload jsonb not null,
  received_at timestamptz not null default now(),
  unique (provider, event_id)
);
create trigger payment_events_append_only before update or delete on payment_events
  for each row execute function forbid_mutation();

create table bank_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  bank_code text not null,
  bank_name text not null,
  account_number text not null check (account_number ~ '^[0-9]{10}$'),
  account_name text not null,
  recipient_codes jsonb not null default '{}'::jsonb,   -- {provider: recipient code}
  created_at timestamptz not null default now(),
  unique (user_id, bank_code, account_number)
);

create table idempotency_keys (
  user_id uuid not null references users(id),
  key text not null check (length(key) between 8 and 80),
  route text not null,
  status_code int not null,
  response jsonb not null,
  created_at timestamptz not null default now(),
  primary key (user_id, key)
);

alter table deposits
  add column provider text check (provider in ('paystack', 'flutterwave')),
  add column channel text,
  add column fee_kobo bigint not null default 0,
  add column checkout_url text,
  add column credited_at timestamptz;
update deposits set provider = psp where provider is null;

alter table withdrawals drop constraint withdrawals_status_check;
alter table withdrawals
  add column provider text check (provider in ('paystack', 'flutterwave')),
  add column bank_account_id uuid references bank_accounts(id),
  add column failure_reason text,
  add column needs_approval boolean not null default false,
  add column approved_by uuid references users(id),
  add constraint withdrawals_status_check check (status in
    ('awaiting_approval', 'pending', 'paid', 'failed', 'reversed', 'rejected'));

-- Paid contest settlement: prizes are booked at confirmation and paid after the 24h hold.
alter table contest_entries
  add column prize_kobo bigint check (prize_kobo >= 0),
  add column prize_paid_at timestamptz;
alter table contests
  add column fee_kobo bigint check (fee_kobo >= 0),
  add column payout_after timestamptz,
  add column paid_out_at timestamptz;
alter table p2p_bets
  add column payout_after timestamptz,
  add column paid_out_at timestamptz,
  add column creator_payout_kobo bigint,
  add column platform_kobo bigint;

-- KYC: what was checked (never the full NIN/BVN), and a stable hash to spot one identity on two accounts.
alter table kyc_records
  add column id_type text check (id_type in ('nin', 'bvn')),
  add column id_last4 text,
  add column identity_hash text,
  add column reason text;
create index kyc_records_identity on kyc_records (identity_hash) where status = 'verified';

-- Referrals: every user gets a code; coins are credited once the friend is verified and has deposited.
alter table users
  add column referral_code text unique,
  add column referred_by uuid references users(id);
alter table referrals
  add column referred_bonus_kobo bigint;

-- Coins expire: each coin credit carries its expiry.
create table bonus_grants (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  amount_kobo bigint not null check (amount_kobo > 0),
  reason text not null,
  expires_at timestamptz not null,
  expired_at timestamptz,
  created_at timestamptz not null default now()
);

alter table wallet_holds enable row level security;
alter table payment_events enable row level security;
alter table bank_accounts enable row level security;
alter table idempotency_keys enable row level security;
alter table bonus_grants enable row level security;
