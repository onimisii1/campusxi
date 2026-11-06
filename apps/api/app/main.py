"""CampusXI API (FastAPI)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import errors, jobs
from app.config import settings
from app.db import connect
from app.engines.scoring.rules import CURRENT_VERSION
from app.middleware import RateLimit, RequestContext, setup_logging
from app.routers import admin, bets, contests, me, payments, public, scorer, teams, wallet


@asynccontextmanager
async def lifespan(_app):
    setup_logging()
    if settings.jobs_enabled:
        jobs.scheduler.start()
    yield
    jobs.scheduler.stop()


app = FastAPI(title="CampusXI API", version="0.5.0", lifespan=lifespan)
app.add_middleware(RateLimit)
app.add_middleware(RequestContext)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                   allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
                   expose_headers=["X-Request-ID"])
errors.install(app)
app.include_router(public.router)
app.include_router(me.router)
app.include_router(teams.router)
app.include_router(contests.router)
app.include_router(bets.router)
app.include_router(scorer.router)
app.include_router(admin.router)
app.include_router(wallet.router)
app.include_router(payments.router)


@app.get("/health")
def health():
    """Liveness plus what an operator needs to know: database, jobs, payments, switches."""
    try:
        with connect() as conn:
            conn.execute("select 1")
        db = "ok"
    except Exception as e:  # noqa: BLE001
        db = f"error: {type(e).__name__}"
    from app.payments import configured
    return {"status": "ok" if db == "ok" else "degraded", "database": db, "scoring_rules": CURRENT_VERSION,
            "jobs": {"enabled": settings.jobs_enabled, "running": jobs.scheduler.running, "last": jobs.status()},
            "payments": [p.name for p in configured()], "kyc_provider": settings.kyc_provider,
            "paid_play_enabled": settings.paid_play_enabled, "result_bets_enabled": settings.result_bets_enabled}
