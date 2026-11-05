# CampusXI

Campus fantasy sports and P2P challenges for university tournaments: build fantasy
teams from real campus athletes, enter contests on each school match, and challenge
other students head-to-head. Stats are entered live by student scorers.

The full product spec is in [`docs/prd/CampusXI_PRD.docx`](docs/prd/CampusXI_PRD.docx) (PDF alongside).

## Repository layout

| Path | Contents |
|---|---|
| `apps/api/` | FastAPI backend |
| `apps/api/app/engines/scoring/` | Per-sport scoring from stat events, team validation, multipliers |
| `apps/api/app/engines/payouts/` | Prize tables (40% fee, top 40% paid), tie splits, minimum fill |
| `apps/api/app/engines/p2p/` | Fantasy H2H and Home/Away bet quotes and settlement |
| `apps/api/tests/` | Golden tests from the PRD's worked examples |
| `apps/web/` | React + TypeScript + Vite PWA shell |
| `docs/prd/` | PRD and the reference script that generated its numbers |

## Running the API tests

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest -q
```

## Running the web app

```bash
cd apps/web
npm install
npm run dev
```

## Build status

Phase 0 (foundation) and Phase 1 (engines and golden tests) of the PRD roadmap.
Next is Phase 2: the Supabase data model from PRD section 7 and the admin setup.
