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

### Accounts (Supabase)

Players sign in with a one-time **email code** (no passwords). The Account page (menu → Account and
security) shows the sign-in email and lets players **change email** (confirmed by a code to the new
address, and to the old one when "Secure email change" is on), **sign out everywhere** (ends every
session) and **delete the account** (`DELETE /me`): cash must be withdrawn and nothing left in play;
coins are forfeited; the team name, photo and sign-in are erased while payment and match records
stay, anonymised (NDPA right to erasure with financial record-keeping).

**Connect a Supabase project:** double-click `apps/api/connect-supabase.cmd` (or
`.\.venv\Scripts\python.exe scripts\connect_supabase.py` in `apps/api`). It asks for the project
URL, the anon/publishable key, the service_role/secret key and the database connection string
(secrets hidden), saves them to `apps/api/.env` and `apps/web/.env.local` (both gitignored), checks
each one, and offers to create the CampusXI tables in the project's database. `--check` re-checks.

**First-time data** (a new database has no schools or admins): from `apps/api`,
`.\.venv\Scripts\python.exe scripts\bootstrap.py add-school "Nile University of Nigeria"`, then, after
signing in once and finishing your profile, `...\bootstrap.py make-admin you@example.com --super`.
`bootstrap.py list` shows what's there. Then load the real NUESA tournament from `data/` with
`load-nuesa.cmd` (or `scripts\load_nuesa.py`): it checks the database is up to date and that the
school and an admin exist, asks before writing, imports squads (jersey colours, captains), fixtures,
results and scorers through the app's own admin import, and refuses to load twice.

**In the Supabase dashboard:**
1. Authentication → Providers → Email: enabled; "Confirm email" on.
2. Authentication → Emails → "Magic Link" template: include `{{ .Token }}` so players get a 6-digit
   code (e.g. "Your CampusXI code is {{ .Token }}"); do the same for "Change Email Address".
3. Authentication → Settings: email OTP length 6; "Secure email change" on.
4. Authentication → URL Configuration: Site URL = the web app's address.
5. Authentication → Emails → SMTP: add your own sender (e.g. Resend). Supabase's built-in sender
   only allows a few emails an hour, which is fine for testing but not for players.
6. Project Settings → JWT Keys: use the new asymmetric signing keys (the API verifies tokens against
   the project's JWKS); otherwise set `SUPABASE_JWT_SECRET` in `apps/api/.env`.

### Going live checklist

1. Production Supabase project; set `DATABASE_URL`, `SUPABASE_URL` (and the web app's
   `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`).
2. **Payment keys** (environment only, never in git): `PAYSTACK_SECRET_KEY`, `FLUTTERWAVE_SECRET_KEY`,
   `FLUTTERWAVE_WEBHOOK_HASH`. Locally, double-click `apps/api/set-payment-keys.cmd` (or in
   PowerShell, from `apps/api`: `.\.venv\Scripts\python.exe scripts\set_payment_keys.py`): it asks for the keys (hidden input), saves them to the gitignored `apps/api/.env`,
   and checks them with read-only calls (`--check` re-checks later). Test keys first; live keys
   must be confirmed by typing LIVE. Point the dashboards' webhooks at
   `https://<api>/payments/paystack/webhook` and `https://<api>/payments/flutterwave/webhook`.
   Set `PUBLIC_APP_URL` to the web app's address (checkout returns there).
3. **KYC provider:** add a class in `app/kyc/` for the chosen provider (Dojah, Prembly, Smile ID, ...),
   register it in `PROVIDERS`, set `KYC_PROVIDER` and a long random `KYC_PEPPER`, then
   `KYC_REQUIRED=true`. The `stub` provider is for test mode only.

   **Until then, ID checks are optional** (`KYC_REQUIRED=false`, the default), SportyBet-style:
   players tick "I'm 18 or older" (`POST /me/confirm-18`) and give their full name as on their bank
   account (`PUT /me/legal-name`; locked once a bank account is saved). Deposits are **bank transfer
   only**, and the provider's verify tells us who paid (name, bank, last four digits). A bank account
   can only be added, and a withdrawal only sent, if its bank-confirmed name matches that full name
   **and** it has paid into the wallet; if the bank names don't line up, an admin approves. Referral
   coins are paid when the friend's first ₦1,000+ deposit comes from an account no other player has
   paid in from.
4. Switches: `PAID_PLAY_ENABLED=true` only once the gaming licence and Paystack's live approval are
   held; `RESULT_BETS_ENABLED=true` only if the licence covers sports betting; background jobs on
   exactly one place (see Hosting below).
5. Check `/health` (database ok, providers listed) and `#/admin/finance` (ledger balanced).

### Hosting (Vercel, free plan)

Two Vercel projects from this one repository, both on the free Hobby plan (it is for non-commercial
use: move to Pro before real money is switched on).

**Live now:** team `campusx-i` (onimisii1's Vercel, GitHub-connected, so every push to `main`
redeploys both). Web app `campusxi` → https://campusxi.site (and www; DNS at Namecheap: `A @` and
`CNAME www` from Vercel's Domains page, next to Resend's mail records). API `campusxi-api` →
https://campusxi-api.vercel.app, region `lhr1` (London, beside the database). Supabase Auth Site
URL is https://campusxi.site. Paystack Live webhook: https://campusxi-api.vercel.app/payments/paystack/webhook.

- **Web app:** Root Directory `apps/web` (settings in `apps/web/vercel.json`). Environment:
  `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL` = the API project's address.
  Hash routes (`#/...`), so no rewrites are needed.
- **API:** Root Directory `apps/api`, framework FastAPI. Vercel's entrypoint is `apps/api/index.py`
  (the normal app plus the jobs route below); `apps/api/vercel.json` gives it 60 s per request.
  Environment: `DATABASE_URL` (Supabase pooler; prefer the Transaction pooler, port 6543),
  `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PAYSTACK_SECRET_KEY` (plus Flutterwave's if used),
  `KYC_PEPPER` (long random), `KYC_REQUIRED=false`, `PUBLIC_APP_URL` = the web address,
  `CORS_ORIGINS=["<web address>"]`, `PAID_PLAY_ENABLED=false`, `RESULT_BETS_ENABLED=false`,
  `JOBS_ENABLED=false` and `CRON_SECRET` (below).
- **Background jobs** (refunds at kick-off, payouts, reminders, reconciliation, coin expiry): Vercel
  only runs the API during a request, so **Supabase Cron** calls `POST /jobs/run/<job>` with
  `Authorization: Bearer <CRON_SECRET>` on each job's interval. Set it up once the API is deployed:
  `apps/api/schedule-jobs.cmd https://<api address>` (or `scripts\schedule_jobs.py`). It turns on
  pg_cron and pg_net, keeps the secret in Supabase Vault, schedules every job in `app/jobs.py`, and
  prints the secret once for Vercel's `CRON_SECRET` (redeploy after setting it). `--test` calls one
  job now, `--status` shows the last calls (200 = ran), `--off` stops them. Jobs are idempotent and
  locked, so a late or repeated call is harmless. Run the scheduler again after adding a job.
- After deploying: Supabase → Authentication → URL Configuration (Site URL and redirect URLs = the
  web address), and the payment webhooks at `https://<api address>/payments/.../webhook`.


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

**Photos.** Players change their picture by tapping it on the profile page; admins upload team
crests (Squads tab) and a match photo (match page) that fills the match screen. Photos are resized
on the phone (avatars 256 px square, crests 256 px PNG, match photos 1280 px JPEG), sent to
`PUT /me/avatar`, `PUT /admin/teams/{id}/logo` or `PUT /admin/matches/{id}/photo`, checked by
their bytes (PNG, JPEG or WebP only, 1.5 MB at most; never SVG) and served from `/media/{id}`.

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

**Swipe & Match** (`#/swipe`, or `#/swipe/<match id>` for one match): open challenges from other
fans as a card deck. Swipe right (or tap ⚡) to take one on, which is an ordinary accept
(`POST /bets/{id}/fills`). A free head-to-head with your only team goes straight through; a stake,
a Home/Away slice or a choice of teams asks first. Swipe left to skip (`POST /bets/{id}/skip`, so it
doesn't come back), ↺ brings the last one back, and "Show the ones you skipped" clears them
(`DELETE /me/bet-skips`). `GET /bets/feed` leaves out your own, ones you've skipped or taken, locked
matches, and stakes you couldn't take. Home, My challenges and each match's Challenges page link to it.

### Local testing (no Supabase needed)

```bash
cd apps/api
.venv/Scripts/python scripts/dev_seed.py --reset
```

The local database holds **only the real NUESA data** from the gitignored `data/` folder
(`nuesa_{football,basketball}_{squads,fixtures,results,result_stats}.csv`; those files hold
students' names, so they never go into git), plus bare Nile test logins: an admin, two scorers and
two fans, with no teams, money or challenges of their own. It starts a local Postgres (in
`apps/api/.devdb`), applies new migrations, and prints `DATABASE_URL`, `SUPABASE_JWT_SECRET` and
sign-in tokens for those logins and a newcomer with no profile. Run the API with those two
variables set, start the web app, and paste a token into the development sign-in (`#/signin`, or
`#/scorer` for scorers). `--reset` wipes the local database and reloads `data/`; `--challenges` has
the two test fans post free challenges on the next NUESA match, so the swipe deck has cards.

## Build status

- Phase 0 (foundation) and Phase 1 (engines): done.
- Phase 2 (data model, admin setup, team builder API): done.
- Phase 3 (scorer API and app, live points, reconciliation, confirmation): done.
- Phase 4 (fan app and free pilot: contests, leaderboards, free challenges, season table): done.
- NUESA 2026/27 (Nile University): competition model, admin screen, tournament pages, profiles: done.
- Phase 5 (wallet, payments, ID checks, paid contests, stakes, result bets, referrals, jobs): done in
  test mode; going live needs the steps in "Going live checklist".
- Design system from the CampusXI designers applied to every screen.
