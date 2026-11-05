# CampusXI — build context for Claude Code

This repo implements the CampusXI PRD (`docs/prd/CampusXI_PRD.docx`). Key constraints
when generating code in this repo:

1. The scoring, payout and P2P engines (`apps/api/app/engines/`) are the core IP.
   Never change them without running their test suite (`apps/api/tests/`), which
   encodes the PRD section 6 worked examples as golden tests.

2. `stat_events`, `p2p_bet_events`, `wallet_ledger` and `audit_log` are append-only.
   Never write code that UPDATEs or DELETEs rows in them; corrections are new
   reversing rows.

3. All money is integer kobo (₦1 = 100 kobo). No floats anywhere in money paths.

4. Follow the schema in PRD section 7 and API contracts in section 8 unless
   explicitly told to deviate.

5. Stack: React+TS+Vite PWA (`apps/web`), FastAPI (`apps/api`), Supabase (Postgres,
   Auth, Realtime), APScheduler, Resend, Paystack. Flag before adding anything else.

6. Build in the phase order of PRD section 10. No UI feature work before the
   Phase 1 engine tests pass. Match-result bets stay behind a feature flag until a
   sports-betting licence is held.

Confirmed product rules (do not change without the product owner):
- Flat 40% platform fee on every contest; the 60% prize pool pays the top 40% of
  ranks, the top 25% in profit (≥ 1.2× entry), the rest get their entry back.
- Standard entry from ₦1,000, plus a ₦400 Mini ticket contest on every match.
  Max 1,000 entrants per contest, max 10 fantasy teams per user per match.
- Uniform athlete pricing (no credit budget). C ×2.5, VC ×2, Key ×1.5.
- P2P: even money, 10% commission on the winner's profit, ₦1,000 minimum stake.
- Whole platform is 18+. Athletes may participate fully, including on their own matches.
