"""Database-level guarantees from the migrations (PRD section 7)."""
import uuid

import psycopg
import pytest

from tests.conftest import make_school, make_user


def test_every_table_has_row_level_security(db):
    rows = db.execute(
        "select relname, relrowsecurity from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r'"
    ).fetchall()
    assert rows and all(r["relrowsecurity"] for r in rows), [r["relname"] for r in rows if not r["relrowsecurity"]]


def _stat_event(db, school=None):
    school = school or make_school(db)
    scorer = make_user(db, school, roles=("player", "scorer"))
    t = db.execute("insert into tournaments (school_id, sport, name, match_minutes) values (%s, 'football', 'Cup', 90)"
                   " returning id", (school,)).fetchone()["id"]
    home, away = (db.execute("insert into teams (tournament_id, name) values (%s, %s) returning id",
                             (t, n)).fetchone()["id"] for n in ("A", "B"))
    athlete = db.execute("insert into athletes (team_id, display_name, position) values (%s, 'P', 'FWD') returning id",
                         (home,)).fetchone()["id"]
    match = db.execute("""insert into matches (tournament_id, home_team_id, away_team_id, scheduled_start,
                          scheduled_minutes, rules_version) values (%s, %s, %s, now(), 90, 'football-v1')
                          returning id""", (t, home, away)).fetchone()["id"]
    return db.execute("""insert into stat_events (match_id, scorer_id, athlete_id, event_type, minute, client_seq)
                         values (%s, %s, %s, 'goal', 10, 1) returning id""", (match, scorer, athlete)).fetchone()["id"]


@pytest.mark.parametrize("sql", ["update stat_events set minute = 11 where id = %s",
                                 "delete from stat_events where id = %s"])
def test_stat_events_are_append_only(db, sql):
    event_id = _stat_event(db)
    with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
        db.execute(sql, (event_id,))


@pytest.mark.parametrize("table", ["stat_events", "wallet_ledger", "p2p_bet_events", "audit_log"])
def test_append_only_tables_reject_truncate(db, table):
    with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
        db.execute(f"truncate {table} cascade")


def test_wallet_ledger_rejects_unbalanced_transaction(db_url):
    with psycopg.connect(db_url) as conn:
        txn = uuid.uuid4()
        conn.execute("insert into wallet_ledger (txn_id, account, amount_kobo, entry_type) "
                     "values (%s, 'user:x:available', 100000, 'deposit')", (txn,))
        with pytest.raises(psycopg.errors.CheckViolation, match="does not balance"):
            conn.commit()


def test_wallet_ledger_accepts_balanced_transaction_and_blocks_edits(db_url):
    with psycopg.connect(db_url) as conn:
        txn = uuid.uuid4()
        for account, amount in (("psp:clearing", -100000), ("user:x:available", 100000)):
            conn.execute("insert into wallet_ledger (txn_id, account, amount_kobo, entry_type) "
                         "values (%s, %s, %s, 'deposit')", (txn, account, amount))
        conn.commit()
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("update wallet_ledger set amount_kobo = 1 where txn_id = %s", (txn,))


def test_users_must_be_18_plus(db):
    school = make_school(db)
    with pytest.raises(psycopg.errors.CheckViolation, match="users_18_plus"):
        db.execute("insert into users (id, school_id, team_name, dob) values (%s, %s, 'kid', current_date - 365 * 17)",
                   (uuid.uuid4(), school))


def test_team_names_unique_ignoring_case(db):
    school = make_school(db)
    make_user(db, school, team_name="Goal Machine")
    with pytest.raises(psycopg.errors.UniqueViolation):
        make_user(db, school, team_name="goal machine")


def test_p2p_matched_amount_cannot_exceed_stake(db):
    school = make_school(db)
    user = make_user(db, school)
    _stat_event(db, school)
    match = db.execute("select id from matches limit 1").fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("""insert into p2p_bets (kind, match_id, creator_id, creator_side, stake_kobo, matched_kobo,
                      visibility) values ('match_result', %s, %s, 'home', 100000, 200000, 'board')""", (match, user))
    with pytest.raises(psycopg.errors.CheckViolation):  # below the N1,000 minimum
        db.execute("""insert into p2p_bets (kind, match_id, creator_id, creator_side, stake_kobo, visibility)
                      values ('match_result', %s, %s, 'home', 40000, 'board')""", (match, user))
