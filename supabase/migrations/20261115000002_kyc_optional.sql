-- KYC optional for now (Nov 2026, SportyBet-style): until ID checks are complete, players give their
-- full name as on their bank account and tick an 18+ box; deposits are by bank transfer, and
-- withdrawals only go back to a bank account in that name that has funded the wallet.
alter table users add column legal_name text;
alter table users add column adult_confirmed_at timestamptz;

-- Who paid a deposit, as the payment provider reports it (bank transfers: sender name, bank and
-- account number; only the last four digits are kept).
alter table deposits add column payer_name text;
alter table deposits add column payer_bank text;
alter table deposits add column payer_account_tail text;
create index deposits_payer on deposits (payer_account_tail) where payer_account_tail is not null;
