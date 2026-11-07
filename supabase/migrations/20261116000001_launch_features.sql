-- Launch features (Nov 2026): team captains (from the squad sheet's note column), and the in-app
-- notifications inbox behind the bell.
alter table athletes add column is_captain boolean not null default false;

create table notifications (
  id bigserial primary key,
  user_id uuid not null references users(id),
  kind text not null,              -- lineup | deadline | challenge_accepted | result | prize
  title text not null,
  body text,
  link text,                       -- in-app route, e.g. #/match/<id>
  ref text not null,               -- what it's about (one notification per user, kind and ref)
  created_at timestamptz not null default now(),
  read_at timestamptz,
  unique (user_id, kind, ref)
);
create index notifications_user on notifications (user_id, created_at desc);
alter table notifications enable row level security;
