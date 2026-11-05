# CampusXI

Campus fantasy sports and P2P challenges for university tournaments: build fantasy
teams from real campus athletes, enter contests on each school match, and challenge
other students head-to-head. Stats are entered live by student scorers.

The full product spec is in [`docs/prd/CampusXI_PRD.docx`](docs/prd/CampusXI_PRD.docx) (PDF alongside).

## Repository layout

| Path | Contents |
|---|---|
| `supabase/migrations/` | Schema (PRD section 7): append-only guards, balanced-ledger check, RLS on every table |
| `supabase/seed/` | Example squad and fixture CSVs in the import format |
| `apps/api/app/engines/` | Scoring, payout and P2P engines (pure Python, no I/O) |
| `apps/api/app/routers/` | FastAPI routes: lobby, profile, team builder, admin setup |
| `apps/api/tests/` | Engine golden tests + integration tests against a real Postgres |
| `apps/web/` | React + TypeScript + Vite PWA shell |
| `docs/prd/` | PRD and the reference script that generated its numbers |

## Database

Migrations are plain SQL, applied with the Supabase CLI:

```bash
supabase link --project-ref <project-ref>
supabase db push
```

Key guarantees enforced by Postgres itself, not just the API:

- `stat_events`, `p2p_bet_events`, `wallet_ledger`, `audit_log` reject UPDATE, DELETE and TRUNCATE.
- Every `wallet_ledger` transaction must sum to zero at commit.
- A P2P bet's matched amount can never exceed its stake; stakes start at ₦1,000.
- Every user is 18+; team names are unique regardless of case.
- Row Level Security is on for every table with no policies, so Supabase's public API can't read them.

## API

Copy `apps/api/.env.example` to `apps/api/.env` and fill in the Supabase values, then:

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Routes so far (Phase 2):

| Area | Routes |
|---|---|
| Lobby | `GET /sports`, `/schools`, `/tournaments`, `/tournaments/{id}`, `/matches`, `/matches/{id}` |
| Profile | `POST /me` (team name, school, 18+ date of birth), `GET /me` |
| Team builder | `POST /matches/{id}/teams`, `PUT /teams/{id}`, `GET /me/teams` |
| Admin | `POST /admin/tournaments`, `.../{id}/squads` (CSV), `.../{id}/fixtures` (CSV), `.../{id}/publish`, `POST /admin/matches/{id}/lineup`, `.../scorers`, `POST /admin/users/{id}/roles`, `POST /admin/schools` |

CSV formats (UTF-8, header row required; see `supabase/seed/` for examples):

- Squads: `team,athlete,position`. Positions: football GK/DEF/MID/FWD; basketball G/F/C; volleyball S/OH/OPP/MB/L.
- Fixtures: `home_team,away_team,scheduled_start,venue`. Times without an offset are read as Lagos time.

An import with any bad row is rejected whole, with every problem listed by row number.

## Tests

```bash
cd apps/api
.venv/Scripts/python -m pytest -q
```

Integration tests need Postgres. They use `TEST_DATABASE_URL` if set (CI uses a Postgres 16
service); otherwise the `pgserver` dev dependency starts a throwaway local server.

## Web app

```bash
cd apps/web
npm install
npm run dev
```

## Build status

- Phase 0 (foundation) and Phase 1 (engines): done.
- Phase 2 (data model, admin setup, team builder API): done.
- Next: Phase 3, the scorer app (live event entry, offline queue, dual-scorer reconciliation).
