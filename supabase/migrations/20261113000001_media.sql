-- Photos: profile pictures, team crests, match photos. Stored by the API (resized on the phone first)
-- and served from /media/{id}; only PNG, JPEG and WebP are accepted (checked by their bytes, never SVG).
create table media (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references users(id),
  kind text not null check (kind in ('avatar', 'team_logo', 'match_photo')),
  content_type text not null check (content_type in ('image/png', 'image/jpeg', 'image/webp')),
  bytes bytea not null check (octet_length(bytes) between 100 and 1572864),
  created_at timestamptz not null default now()
);
alter table media enable row level security;

alter table users add column avatar_url text;
alter table matches add column photo_url text;

-- Team logos may now also point at an uploaded image.
alter table teams drop constraint teams_logo_url_check;
alter table teams add constraint teams_logo_url_check
  check (logo_url is null or ((logo_url ~ '^https://' or logo_url ~ '^/media/[0-9a-f-]{36}$') and length(logo_url) <= 500));
