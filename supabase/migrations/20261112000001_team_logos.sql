-- Team crests for the design's round badges. An https image URL (e.g. Supabase Storage or the
-- department's own site); without one the app draws the jersey colour with the team code.
alter table teams
  add column logo_url text check (logo_url is null or (logo_url ~ '^https://' and length(logo_url) <= 500));
