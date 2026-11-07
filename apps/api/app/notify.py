"""In-app notifications (the bell). One row per player, kind and subject (ref), so firing the same
event twice never doubles up. Sent when line-ups are out, an hour before a match locks, when someone
takes your challenge, when a result is confirmed, and when winnings reach your wallet."""
from datetime import timedelta

from app.matches import MATCH_SQL


def _naira(kobo: int) -> str:
    return f"₦{kobo / 100:,.0f}" if kobo % 100 == 0 else f"₦{kobo / 100:,.2f}"


def notify(conn, user_ids, kind: str, ref, title: str, body: str | None = None, link: str | None = None,
           now=None) -> int:
    rows = [(u, kind, title, body, link, str(ref), now) for u in dict.fromkeys(user_ids) if u]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """insert into notifications (user_id, kind, title, body, link, ref, created_at)
               values (%s, %s, %s, %s, %s, %s, coalesce(%s, now())) on conflict (user_id, kind, ref) do nothing""",
            rows)
    return len(rows)


def match_fans(conn, match_id) -> list:
    """Players with a team for this match."""
    return [r["user_id"] for r in conn.execute(
        "select distinct user_id from fantasy_teams where match_id = %s", (match_id,)).fetchall()]


def _title(m) -> str:
    return f"{m['home_team']} v {m['away_team']}"


def lineups_out(conn, m, now) -> None:
    notify(conn, match_fans(conn, m["id"]), "lineup", m["id"], f"Line-ups are out: {_title(m)}",
           "Check your team: players who aren't starting score nothing.", f"#/match/{m['id']}/teams", now)


def result_confirmed(conn, m, home_score, away_score, now) -> None:
    notify(conn, match_fans(conn, m["id"]), "result", m["id"],
           f"Full time: {m['home_team']} {home_score}–{away_score} {m['away_team']}",
           "Final points and contest ranks are in.", f"#/match/{m['id']}", now)


def challenge_taken(conn, bet, taker_name: str, now) -> None:
    m = conn.execute(MATCH_SQL + " where m.id = %s", (bet["match_id"],)).fetchone()
    stake = f" for {_naira(bet['stake_kobo'])}" if bet["stake_kobo"] else ""
    notify(conn, [bet["creator_id"]], "challenge_accepted", f"{bet['id']}:{taker_name}",
           f"{taker_name} took on your challenge{stake}", _title(m), "#/challenges", now)


def winnings_paid(conn, prizes: dict, what: str, ref, now) -> None:
    for uid, kobo in prizes.items():
        if kobo and kobo > 0:
            notify(conn, [uid], "prize", f"{ref}:{uid}", f"You won {_naira(kobo)}",
                   f"Your {what} winnings are in your wallet.", "#/wallet", now)


def deadline_reminders(conn, now, within=timedelta(hours=1)) -> dict:
    """Matches locking within the hour: remind every player at that school (those with a team can
    still change it; those without can still make one)."""
    sent = 0
    for m in conn.execute(MATCH_SQL + """ where t.status = 'published' and m.status in ('scheduled', 'lineup_out')
                                           and m.scheduled_start > %s and m.scheduled_start <= %s""",
                          (now, now + within)).fetchall():
        users = [r["id"] for r in conn.execute(
            "select id from users where school_id = %s and deleted_at is null", (m["school_id"],)).fetchall()]
        sent += notify(conn, users, "deadline", m["id"], f"{_title(m)} locks within the hour",
                       "Last chance to pick or change your team.", f"#/match/{m['id']}", now)
    return {"sent": sent}
