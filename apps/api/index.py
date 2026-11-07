"""Vercel entrypoint for the CampusXI API: the normal app, plus one protected route for scheduled jobs.

Vercel runs the API only while a request is in flight, so the in-process job thread (JOBS_ENABLED) can't
run there. Instead Supabase Cron (pg_cron + pg_net, set up by scripts/schedule_jobs.py) calls
    POST /jobs/run/<job name>    with    Authorization: Bearer <CRON_SECRET>
on each job's schedule. Every job is idempotent and takes a Postgres advisory lock (app/jobs.py), so a
late, repeated or overlapping call is harmless. Keep JOBS_ENABLED=false on Vercel.

Locally nothing changes: `uvicorn app.main:app` as before (this file is only Vercel's entrypoint).
"""
import hmac
import os

from fastapi import Header, HTTPException

from app import jobs
from app.main import app

__all__ = ["app"]


@app.post("/jobs/run/{name}", include_in_schema=False)
def run_scheduled_job(name: str, authorization: str = Header(default="")):
    secret = os.environ.get("CRON_SECRET", "")
    if not secret or not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
        raise HTTPException(status_code=401, detail="not allowed")
    job = next((j for j in jobs.JOBS if j.name == name), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job called {name}")
    return {"job": name, "result": jobs.run_job(job)}
