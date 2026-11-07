"""Background jobs: refunds at kick-off, prize payouts after the dispute hold, payment reconciliation,
coin expiry. Each job is idempotent and runs in its own transaction under a Postgres advisory lock,
so several API instances (or a cron run) never double-run it.

    JOBS_ENABLED=true uvicorn app.main:app      # a light in-process scheduler thread
    python -m app.jobs                          # run every job once (e.g. from cron)

No scheduler library: a small thread loop is enough for minute-level jobs.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.db import connect

log = logging.getLogger("campusxi.jobs")


@dataclass
class Job:
    name: str
    every_seconds: int
    run: callable
    last_run: datetime | None = None
    last_result: object = None
    last_error: str | None = None
    next_at: float = field(default=0.0)


def _refund_at_lock(conn, now):
    from app.settlement import refund_at_lock
    return refund_at_lock(conn, now)


def _release_payouts(conn, now):
    from app.settlement import release_payouts
    return release_payouts(conn, now)


def _reconcile(conn, now):
    from app.payments import configured
    from app.payments.service import reconcile
    return reconcile(conn, now) if configured() else {"skipped": "no payment provider configured"}


def _expire_bonus(conn, now):
    from app.wallet import expire_bonus
    return {"expired_kobo": expire_bonus(conn, now)}


def _deadline_reminders(conn, now):
    from app.notify import deadline_reminders
    return deadline_reminders(conn, now)


JOBS = [
    Job("refund_at_lock", 60, _refund_at_lock),
    Job("deadline_reminders", 300, _deadline_reminders),
    Job("release_payouts", 300, _release_payouts),
    Job("reconcile_payments", 900, _reconcile),
    Job("expire_bonus", 3600, _expire_bonus),
]


def run_job(job: Job, now: datetime | None = None, url: str | None = None):
    now = now or datetime.now(timezone.utc)
    with connect(url) as conn:
        with conn.transaction():
            got = conn.execute("select pg_try_advisory_xact_lock(hashtextextended(%s, 0)) as ok",
                               (f"job:{job.name}",)).fetchone()["ok"]
            if not got:
                return {"skipped": "running elsewhere"}
            result = job.run(conn, now)
    job.last_run, job.last_result, job.last_error = now, result, None
    log.info("job %s done: %s", job.name, result)
    return result


def run_all(now=None, url=None) -> dict:
    out = {}
    for job in JOBS:
        try:
            out[job.name] = run_job(job, now, url)
        except Exception as e:  # noqa: BLE001  (one failing job mustn't stop the others)
            job.last_error = str(e)
            log.exception("job %s failed", job.name)
            out[job.name] = {"error": str(e)}
    return out


class Scheduler:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="campusxi-jobs", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self):
        while not self._stop.is_set():
            mono = time.monotonic()
            for job in JOBS:
                if mono >= job.next_at:
                    job.next_at = mono + job.every_seconds
                    try:
                        run_job(job)
                    except Exception as e:  # noqa: BLE001
                        job.last_error = str(e)
                        log.exception("job %s failed", job.name)
            self._stop.wait(5)


scheduler = Scheduler()


def status() -> list:
    return [{"name": j.name, "every_seconds": j.every_seconds, "last_run": j.last_run, "last_error": j.last_error}
            for j in JOBS]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_all())
