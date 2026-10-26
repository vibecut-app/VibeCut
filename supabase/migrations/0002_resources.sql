-- VibeCut: My resources (web/backend/resources.py) -- the caption looks,
-- animations, transitions, effects, shot settings and songs a person saved
-- to keep. Same table, one more kind; a deleted one is a row whose value is
-- {"deleted": true}, so every computer drops it.

alter table preferences drop constraint if exists preferences_kind_check;
alter table preferences add constraint preferences_kind_check
  check (kind in ('default', 'rule', 'profile', 'vibe', 'resource'));
