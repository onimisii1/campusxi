"""CampusXI API (FastAPI)."""
from fastapi import FastAPI

from app import errors
from app.engines.scoring.rules import CURRENT_VERSION
from app.routers import admin, me, public, teams

app = FastAPI(title="CampusXI API", version="0.2.0")
errors.install(app)
app.include_router(public.router)
app.include_router(me.router)
app.include_router(teams.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok", "scoring_rules": CURRENT_VERSION}
