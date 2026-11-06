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

Routes so far (Phases 2–4):

| Area | Routes |
|---|---|
| Lobby | `GET /sports`, `/sports/{code}/rules`, `/schools`, `/tournaments/{id}/standings`, `/tournaments/{id}/stats`, `/tournaments/{id}/bracket`, `/athletes/{id}`, `/tournaments`, `/tournaments/{id}`, `/tournaments/{id}/leaderboard`, `/matches`, `/matches/{id}`, `/matches/{id}/live` |
| Profile | `POST /me` (team name, school, 18+ date of birth), `GET /me` |
| Team builder | `POST /matches/{id}/teams`, `PUT /teams/{id}`, `GET /me/teams`, `GET /teams/{id}/breakdown` |
| Contests | `GET /matches/{id}/contests`, `POST /contests/{id}/entries`, `DELETE /entries/{id}`, `GET /contests/{id}/leaderboard`, `GET /contests/{id}/payout-preview`, `POST /admin/matches/{id}/contests` |
| Challenges | `POST /bets`, `GET /matches/{id}/bets`, `GET /bets/invite/{token}`, `POST /bets/{id}/fills`, `POST /bets/{id}/cancel`, `GET /me/bets` |
| Scorer | `GET /scorer/matches`, `GET /scorer/matches/{id}`, `POST /scorer/matches/{id}/events`, `POST /scorer/matches/{id}/submit` |
| Admin setup | `POST /admin/tournaments`, `.../{id}/squads` (CSV), `.../{id}/fixtures` (CSV), `.../{id}/publish`, `POST /admin/matches/{id}/lineup`, `.../scorers`, `POST /admin/users/{id}/roles`, `POST /admin/schools` |
| Admin results | `GET /admin/matches/{id}/reconcile`, `POST /admin/matches/{id}/confirm`, `.../reopen`, `.../abandon`, `.../postpone`, `.../kickoff`, `.../walkover` |
| Competition | `GET /admin/tournaments/{id}/matches`, `GET /admin/users?role=scorer`, `POST /admin/tournaments/{id}/knockout`, `.../results` (CSV), `.../result-stats` (CSV), `POST /scorer/matches/{id}/kickoff` |

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

### Free pilot (Phase 4)

- Every imported match gets a free contest automatically (1,000 spots, up to 10 teams per player);
  admins can add more with sponsor prize text. Leaderboards are live from kick-off.
- Free head-to-head challenges: post on the match's open board or share a link. The creator's
  team stays hidden until kick-off.
- Confirming a result records final contest ranks and challenge results; abandoning voids them.
- The season table adds up each player's best team from every confirmed match.
- Paid entry and stakes are switched off (`PAID_PLAY_ENABLED=false`) until Phase 5.

### Running a competition

- **Kick off now** (admin screen or scorer app) starts the match clock when the referee does;
  teams still lock at the scheduled time. Delay buttons move the kick-off and reopen teams.
- **Walkover:** shown as voided (no scoreline); the winner still gets the league points;
  fantasy contests and challenges for that match are voided.
- **League tables:** football W3 D1 L0 (points, goal difference, goals scored); basketball W2 L0
  (points, points difference, points scored). Teams level on every tiebreak share a rank ("2=").
- **Golden boot** (goals, then assists, then fewer matches) and **basketball MVP**
  (PTS + 1.2 REB + 1.5 AST + 2.5 STL + 2 BLK), from official stats.
- **Knockouts** are paired by the admin; the bracket suggests 1v4 and 2v3 from the table.
- **Squad audit:** admins fix names and positions (Squads tab) until a player has played, and set the match length.
- **Past results** (before the app was used) import as `code,home_team,away_team,home_score,away_score,played_at`,
  with optional stat lines `code,team,athlete,goals,assists` or `...,pts,reb,ast,stl,blk`.
- Basketball is positionless (any 8, max 5 from one side) and scored with the MVP weights
  (`basketball-v2-draft`); matches pinned to v1 keep v1.

### Late joining

Contests (and new teams) stay open after kick-off until 67% of the scheduled match minutes,
judged by the later of the clock and the latest recorded event. A late entry only scores what
happens after it joins: the API stores the newest stat event id at that moment and counts
`points now − points as of that event`, so corrections to earlier events can't leak in. A late
paid entry costs 150% of the entry fee; the extra goes into the prize pool, but the prize table
is the same as everyone else's. Teams built late can't be edited. Untimed sports (volleyball)
have no late window.

CSV formats (UTF-8, header row required; see `supabase/seed/` for examples):

- Squads: `team,athlete,position[,jersey]`. Positions: football GK/DEF/MID/FWD; basketball G/F/C;
  volleyball S/OH/OPP/MB/L. Team-sheet codes are accepted too (LB, CB, CM, DM, AM, ST, RW, PG, SF,
  Libero, …). `jersey` is a colour name (white, black, royal blue, …) or `#RRGGBB`; it sets the
  team's shirt colour in the app and only needs to appear once per team.
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

The fan app is the default route: a sport slider over every event for that sport, a match card
(your points / average / highest, deadline, and buttons for Pick Team, Contests, Challenges and
Live points), a pitch-view team builder with Quick pick and search, leaderboards that refresh
themselves while a match is live, season tables and challenge invite links. The menu button
(top left) opens the profile.

Contests are cards with the prize, a filled-spots bar and a Join button that opens a sheet to
choose a team. A contest's page has Winnings (prize table if it fills, or as it stands now),
Rules and Entries tabs, with Leaderboard first once the match starts. The team builder has
position tabs that show how many more of each you need, plus a Line-ups tab listing both squads
side by side, and each player's points in their team's last match.

After saving a team, a sheet offers the open contests to join with it; every team card shows the
contests it's in. The contests page has All contests / My contests / My teams tabs, sort chips
and groups (Free, Mega, Head-to-head, Mini). Each tournament has a page with fixtures and results,
the league table, golden boot or MVP, and the bracket, each shareable as an image (Canvas, Web
Share API, download fallback). Players have profile pages with match-by-match fantasy points.
Admins run match day at `#/admin`: kick-offs, delays, walkovers, scorers, line-ups, results,
CSV imports and knockouts.

Production builds register a service worker (`vite-plugin-pwa`): the app installs to the home
screen and opens without signal. Only purely public match data is cached by it.
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

This starts a local Postgres (in `apps/api/.devdb`), applies any new migrations, creates a demo
match 20 minutes from now (`KICKOFF_IN_MINUTES` to change) with two scorers assigned, and prints
`DATABASE_URL`, `SUPABASE_JWT_SECRET` and sign-in tokens for an admin, two scorers, two fans and a
newcomer with no profile. Run the API with those two variables set, start the web app, and paste
a token into the development sign-in (`#/signin`, or `#/scorer` for scorers). `--reset` wipes the
local database first.

`--nuesa` also imports a real tournament from `data/nuesa_{football,basketball}_{squads,fixtures}.csv`.
`data/` is gitignored because those files hold students' names; without them the step is skipped.

## Build status

- Phase 0 (foundation) and Phase 1 (engines): done.
- Phase 2 (data model, admin setup, team builder API): done.
- Phase 3 (scorer API and app, live points, reconciliation, confirmation): done.
- Phase 4 (fan app and free pilot: contests, leaderboards, free challenges, season table): done.
- NUESA 2026/27 (Nile University): competition model, admin screen, tournament pages, profiles: done.
- Next: the pilot itself (needs a Supabase project and a school sports week), then Phase 5
  (KYC, wallet, paid contests), which is gated on the licence and school approval.
