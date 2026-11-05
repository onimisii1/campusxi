"""CampusXI API (FastAPI). Phase 0 shell: feature routes arrive with the data model in Phase 2."""
from fastapi import FastAPI

from app.engines.scoring.rules import CURRENT_VERSION

app = FastAPI(title="CampusXI API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "scoring_rules": CURRENT_VERSION}
