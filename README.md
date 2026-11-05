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

Routes so far (Phases 2–3):

| Area | Routes |
|---|---|
| Lobby | `GET /sports`, `/schools`, `/tournaments`, `/tournaments/{id}`, `/matches`, `/matches/{id}`, `/matches/{id}/live` |
| Profile | `POST /me` (team name, school, 18+ date of birth), `GET /me` |
| Team builder | `POST /matches/{id}/teams`, `PUT /teams/{id}`, `GET /me/teams`, `GET /teams/{id}/breakdown` |
| Scorer | `GET /scorer/matches`, `GET /scorer/matches/{id}`, `POST /scorer/matches/{id}/events`, `POST /scorer/matches/{id}/submit` |
| Admin setup | `POST /admin/tournaments`, `.../{id}/squads` (CSV), `.../{id}/fixtures` (CSV), `.../{id}/publish`, `POST /admin/matches/{id}/lineup`, `.../scorers`, `POST /admin/users/{id}/roles`, `POST /admin/schools` |
| Admin results | `GET /admin/matches/{id}/reconcile`, `POST /admin/matches/{id}/confirm`, `.../reopen`, `.../abandon`, `.../postpone` |

### Scoring workflow

1. An admin assigns one or two scorers. The first is **primary**: their stream drives live points.
2. Scoring opens 30 minutes before kick-off once the line-up is published. The first event
   makes the match `live`, which locks fantasy teams.
3. Events are append-only and idempotent by `client_seq`: resending is harmless, undo is a new
   reversing event. Each event in a batch is accepted, a duplicate, or rejected with a reason.
4. Each scorer submits their final score; when all have, the match is `final_pending`.
5. The admin compares the streams (`/reconcile`), can reopen a submission for fixes, then
   confirms the result and names the official stream. Payouts wait 24 hours after that.

Live clean sheets only count minutes actually played, so they appear (provisionally) once a
defender has been on the pitch for 60% of the match and disappear if their side concedes.

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

The scorer app is at `#/scorer`. It keeps working offline: every tap is saved on the phone
first and sent when the connection returns, and the last-seen matches reopen without signal.

Sign-in uses Supabase email one-time codes. Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
(see `apps/web/.env.example`), and make sure the Supabase "Magic Link" email template includes
`{{ .Token }}` so users receive a code rather than only a link.

### Local scorer testing (no Supabase needed)

```bash
cd apps/api
.venv/Scripts/python scripts/dev_seed.py
```

This starts a local Postgres (in `apps/api/.devdb`), creates a demo match 10 minutes from now
with two scorers assigned, and prints `DATABASE_URL`, `SUPABASE_JWT_SECRET` and sign-in tokens.
Run the API with those two variables set, start the web app, open `#/scorer`, and paste a scorer
token into the development sign-in.

## Build status

- Phase 0 (foundation) and Phase 1 (engines): done.
- Phase 2 (data model, admin setup, team builder API): done.
- Phase 3 (scorer API and app, live points, reconciliation, confirmation): done.
- Next: Phase 4, the fan app and free pilot (lobby, team builder UI, free contests, leaderboards).
