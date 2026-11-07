import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/.env, wherever the API is started from; the test suite ignores it (CAMPUSXI_IGNORE_DOTENV).
ENV_FILE = None if os.environ.get("CAMPUSXI_IGNORE_DOTENV") else Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/campusxi"
    # Supabase Auth. Tokens are verified against the project's JWKS; set
    # supabase_jwt_secret only for projects still on the legacy HS256 secret (and tests).
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    # Server-only key, used to delete a player's sign-in when they delete their account.
    supabase_service_role_key: str = ""
    jwt_audience: str = "authenticated"
    # Paid contests and stakes need the fantasy licence, school approval and payments (Phase 5).
    paid_play_enabled: bool = False
    # Match-result bets are sports betting: off until a sports-betting licence is held.
    result_bets_enabled: bool = False
    # While paid play is on, every open match automatically gets a ₦400 Mini and a ₦1,000 Mega with
    # these many spots (0 skips one); admins can still add more contests by hand.
    auto_paid_contests: bool = True
    default_mini_capacity: int = 20
    default_mega_capacity: int = 50
    # ---- money (all integer kobo) ----
    min_deposit_kobo: int = 10_000                 # N100
    daily_deposit_limit_kobo: int = 5_000_000      # N50,000 a day unless the user sets lower
    min_withdrawal_kobo: int = 50_000              # N500
    withdrawal_approval_over_kobo: int = 10_000_000  # above N100,000 (and every first withdrawal) an admin approves
    # Referral coins: stake-only, never withdrawn; winnings from them are cash.
    referral_bonus_kobo: int = 20_000              # N200 to the referrer
    referred_bonus_kobo: int = 10_000              # N100 to the new player
    referral_min_deposit_kobo: int = 100_000       # friend must be verified and deposit N1,000 first
    bonus_max_share_bps: int = 5000                # coins can pay at most 50% of an entry or stake
    bonus_expiry_days: int = 90
    payout_hold_hours: int = 24                    # prizes wait out the dispute window
    # KYC is optional until a provider is live (Nov 2026). Meanwhile, SportyBet-style: players tick 18+,
    # give their full name as on their bank account, deposit by bank transfer, and withdraw only to a
    # bank account in that name that has funded the wallet. KYC_REQUIRED=true restores ID checks.
    kyc_required: bool = False
    # KYC: "stub" in test mode; a real provider (Dojah, Prembly, ...) plugs into app/kyc.
    kyc_provider: str = "stub"
    kyc_pepper: str = "dev-only-pepper"            # hashes NIN/BVN so one identity can't verify two accounts
    # Payments: test keys by default. Live keys only ever come from the environment.
    paystack_secret_key: str = ""
    flutterwave_secret_key: str = ""
    flutterwave_webhook_hash: str = ""
    payment_providers: list[str] = ["paystack", "flutterwave"]   # order = preference; the next is the fallback
    public_app_url: str = "http://localhost:5180"  # where checkout sends players back to
    # Background jobs (refunds at lock, payouts, reconciliation, coin expiry) in this process.
    jobs_enabled: bool = False
    rate_limit_enabled: bool = True
    # Every match gets one free contest automatically when fixtures are imported.
    default_free_contest_capacity: int = 1000
    # Browser origins allowed to call the API (comma-separated in the environment).
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5180"]


settings = Settings()
