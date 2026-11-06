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

## Real money (Phase 5)

All money is integer kobo in the append-only, double-entry `wallet_ledger`; `app/wallet.py` is the
only code that writes it, and every transaction must balance.

- **Accounts:** cash (withdrawable) and referral **coins** (stake-only, never withdrawn, expire after
  90 days), plus held versions of each. Coins pay at most 50% of an entry or stake; winnings are
  always paid as cash; refunds go back where they came from (coins as coins).
- **Who may play:** `PAID_PLAY_ENABLED`, an ID check (NIN or BVN, 18+; only the last 4 digits and a
  salted hash are stored), not on a self-imposed break, inside daily deposit/stake limits (lowering
  a limit is immediate, raising it waits 24h). Scorers can't stake on matches they score; linked
  accounts (same bank account or device) can't bet against each other.
- **Paid contests:** the ₦400 Mini or ₦1,000 and up, fundable at the 40% fee. The fee is held on
  join and released on leave; at confirmation the entries are captured into a pot and prizes booked;
  cash is paid 24 hours later (dispute hold). Contests short of their minimum are refunded at kick-off.
- **Stakes:** fantasy H2H (winner gets both stakes less 10% commission on the winnings) and Home/Away
  result bets (`RESULT_BETS_ENABLED`, needs the sports-betting licence) with multi-challenger slices.
  Draws, walkovers and abandoned matches refund everyone.
- **Payments:** Paystack first, Flutterwave as the fallback, behind one interface (`app/payments/`).
  Deposits are credited once, only after a server-side verify agrees on the amount; webhooks are
  signature-checked and de-duplicated. Withdrawals go only to a bank account in the verified name;
  the first one and anything over ₦100,000 wait for an admin (`#/admin/finance`).
- **Referrals:** both players get coins once the invited friend is verified and deposits ₦1,000.
- **Background jobs** (`JOBS_ENABLED=true` or `python -m app.jobs` from cron): refunds at kick-off,
  prize payouts after the hold, payment reconciliation, coin expiry. Each is idempotent and
  advisory-locked, so only one instance runs it.
- **Safety:** `Idempotency-Key` on every money POST, rate limits on money and ID routes, JSON request
  logs with request IDs, `/health` with database, jobs, providers and switches.

### Going live checklist

1. Production Supabase project; set `DATABASE_URL`, `SUPABASE_URL` (and the web app's
   `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`).
2. **Payment keys** (environment only, never in git): `PAYSTACK_SECRET_KEY`, `FLUTTERWAVE_SECRET_KEY`,
   `FLUTTERWAVE_WEBHOOK_HASH`. Point the dashboards' webhooks at
   `https://<api>/payments/paystack/webhook` and `https://<api>/payments/flutterwave/webhook`.
   Set `PUBLIC_APP_URL` to the web app's address (checkout returns there).
3. **KYC provider:** add a class in `app/kyc/` for the chosen provider (Dojah, Prembly, Smile ID, ...),
   register it in `PROVIDERS`, set `KYC_PROVIDER` and a long random `KYC_PEPPER`. The `stub` provider
   is for test mode only.
4. Switches: `PAID_PLAY_ENABLED=true`; `RESULT_BETS_ENABLED=true` only if the licence covers sports
   betting; `JOBS_ENABLED=true` on exactly one API instance (or run the cron entry instead).
5. Check `/health` (database ok, providers listed, jobs running) and `#/admin/finance` (ledger balanced).

Local demo without a provider: `scripts/dev_seed.py --money` verifies the demo fans and credits test
cash straight into the local ledger, then adds paid contests; run the API with
`PAID_PLAY_ENABLED=true RESULT_BETS_ENABLED=true`.

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

**Design.** The whole app follows the CampusXI designers' mock-up: near-black page, charcoal
rounded cards, a neon-lime accent (dark text on lime), pill chips and round icon buttons. Tokens
live at the end of `apps/web/src/index.css` ("CampusXI design system"). Home is the greeting row
(avatar opens the menu, wallet chip, bell), "Choose your *Favourite game*", sport pills, and the
top event as a lime card stacked over the next match. Every other screen has a centred title
between a round back button and a round menu button. Fixtures use the day strip and live-score
cards with a fans row; the match page is a scoreboard panel with the clock's lime progress knob.

The fan app: event cards for every match of the chosen sport, a match page (your points / average
/ highest, deadline, and buttons for Pick Team, Contests, Challenges and Live points), a
pitch-view team builder with Quick pick and search, leaderboards that refresh themselves while a
match is live, season tables and challenge invite links.

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
- Phase 5 (wallet, payments, ID checks, paid contests, stakes, result bets, referrals, jobs): done in
  test mode; going live needs the steps in "Going live checklist".
- Design system from the CampusXI designers applied to every screen.
