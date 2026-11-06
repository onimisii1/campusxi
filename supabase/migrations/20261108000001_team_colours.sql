-- Real jersey colours per team (from the squad import), used for shirts in the app.
alter table teams
  add column colour text check (colour ~ '^#[0-9A-Fa-f]{6}$');
