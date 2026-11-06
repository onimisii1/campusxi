"""CampusXI API (FastAPI)."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import errors
from app.config import settings
from app.engines.scoring.rules import CURRENT_VERSION
from app.routers import admin, bets, contests, me, payments, public, scorer, teams, wallet

app = FastAPI(title="CampusXI API", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                   allow_headers=["Authorization", "Content-Type"])
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
    return {"status": "ok", "scoring_rules": CURRENT_VERSION}
