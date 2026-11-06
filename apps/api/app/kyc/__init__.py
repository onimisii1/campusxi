"""Identity checks for paid play (NIN or BVN with date of birth). The provider is chosen later
(Dojah, Prembly, Smile ID, ...): each is a small class with `verify`. In test mode the stub is used."""
import hashlib
from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class KycResult:
    status: str                 # verified | rejected
    reference: str
    verified_name: str | None = None
    dob: object | None = None   # date, as the provider holds it
    reason: str | None = None


class StubProvider:
    """Test mode only. Numbers ending 0000 fail ("no record"); 9999 returns a date of birth under 18;
    anything else verifies with the name and date of birth the player gave."""
    name = "stub"

    def verify(self, id_type: str, number: str, dob, full_name: str) -> KycResult:
        from datetime import date
        ref = f"stub-{id_type}-{number[-4:]}"
        if number.endswith("0000"):
            return KycResult("rejected", ref, reason="no record found for that number")
        if number.endswith("9999"):
            return KycResult("verified", ref, full_name, date(2010, 1, 1))
        return KycResult("verified", ref, full_name, dob)


PROVIDERS = {"stub": StubProvider}


def provider():
    return PROVIDERS[settings.kyc_provider]()


def identity_hash(id_type: str, number: str) -> str:
    return hashlib.sha256(f"{settings.kyc_pepper}:{id_type}:{number}".encode()).hexdigest()
