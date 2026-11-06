-- Late joining (agreed 6 Nov 2026): contests and new teams can be joined until 67% of the
-- match. Points recorded before joining don't count. A late entry pays +50% (it grows the pool)
-- and is paid by the same prize table as everyone else.
--
-- "Before joining" is a watermark: the highest stat_events.id recorded for the match when the
-- player joined. Points = total - total as of the watermark. Using the event sequence (not
-- wall clocks) keeps it fair with stoppage time, late kick-offs and offline scorer phones.

alter table contest_entries
  add column fee_kobo bigint not null default 0 check (fee_kobo >= 0),
  add column late_after_event_id bigint,
  add column late_elapsed_minutes int check (late_elapsed_minutes >= 0);

alter table fantasy_teams
  add column late_after_event_id bigint,
  add column late_elapsed_minutes int check (late_elapsed_minutes >= 0);
