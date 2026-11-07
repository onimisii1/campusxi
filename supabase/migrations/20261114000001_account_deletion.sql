-- Account deletion (NDPA): personal details are erased; money and match records stay, anonymised,
-- because financial records must be kept. A deleted profile can't be used again.
alter table users add column deleted_at timestamptz;
