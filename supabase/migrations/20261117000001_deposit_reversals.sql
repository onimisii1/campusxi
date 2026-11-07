-- Deposits the provider takes back after crediting (refund or chargeback). The credited cash is
-- taken back from the player's wallet; whatever was already spent or withdrawn is booked to
-- platform:reversal_loss, and the player's cash play is frozen until an admin clears it.
alter table deposits drop constraint deposits_status_check;
alter table deposits add constraint deposits_status_check check (status in ('pending', 'success', 'failed', 'reversed'));
alter table deposits add column reversed_at timestamptz;
alter table deposits add column reversal_reason text;
alter table deposits add column shortfall_kobo bigint not null default 0;

alter table wallet_ledger drop constraint wallet_ledger_entry_type_check;
alter table wallet_ledger add constraint wallet_ledger_entry_type_check check (entry_type in (
  'deposit', 'withdrawal', 'withdrawal_reversal', 'hold', 'release', 'entry_fee', 'prize', 'stake',
  'payout', 'refund', 'rake', 'commission', 'bonus', 'bonus_expiry', 'deposit_reversal'));

-- Cash play (deposits, stakes, withdrawals) is blocked while this is set; free play is unaffected.
alter table users add column money_frozen_at timestamptz;
alter table users add column money_frozen_reason text;
